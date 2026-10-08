import json
import time
import uuid
from pathlib import Path

import agent.tools
import agent.finance_agent as finance_agent_module

from agent.finance_agent import FinanceAgent
from tests.run_first_tool_evals import (
    arguments_match,
    load_eval_cases,
    resolve_expected_args,
)

RESULTS_FILE = Path(__file__).parent / "agent_loop_eval_results.json"

# ---------------------------------------------------------------------------
# Deterministic fake data
# ---------------------------------------------------------------------------

FAKE_TRANSACTIONS = [
    {
        "Date": "2026-09-02",
        "Month": "Sep",
        "From Account": "HDFC",
        "To Account": "",
        "Type": "Expense",
        "Category": "Food",
        "Reason": "Dinner",
        "Amount": 800,
    },
    {
        "Date": "2026-09-05",
        "Month": "Sep",
        "From Account": "HDFC",
        "To Account": "",
        "Type": "Expense",
        "Category": "Travel",
        "Reason": "Cab",
        "Amount": 500,
    },
    {
        "Date": "2026-09-10",
        "Month": "Sep",
        "From Account": "ICICI",
        "To Account": "",
        "Type": "Expense",
        "Category": "Food",
        "Reason": "Lunch",
        "Amount": 1200,
    },
    {
        "Date": "2026-09-15",
        "Month": "Sep",
        "From Account": "HDFC",
        "To Account": "",
        "Type": "Expense",
        "Category": "Shopping",
        "Reason": "Clothes",
        "Amount": 2000,
    },
    {
        "Date": "2026-08-05",
        "Month": "Aug",
        "From Account": "HDFC",
        "To Account": "",
        "Type": "Expense",
        "Category": "Food",
        "Reason": "Dinner",
        "Amount": 1000,
    },
    {
        "Date": "2026-08-12",
        "Month": "Aug",
        "From Account": "HDFC",
        "To Account": "",
        "Type": "Expense",
        "Category": "Travel",
        "Reason": "Cab",
        "Amount": 700,
    },
    {
        "Date": "2026-08-20",
        "Month": "Aug",
        "From Account": "ICICI",
        "To Account": "",
        "Type": "Expense",
        "Category": "Shopping",
        "Reason": "Shoes",
        "Amount": 1500,
    },
]


# ---------------------------------------------------------------------------
# Fake services
# ---------------------------------------------------------------------------

class FakeUserService:
    def __init__(self):
        self.users = {
            "Shashwath": {
                "username": "Shashwath",
                "sheet_name": "Shash",
                "telegram_chat_id": "111",
                "allowed": "TRUE",
            },
            "Uha": {
                "username": "Uha",
                "sheet_name": "Uha",
                "telegram_chat_id": "222",
                "allowed": "TRUE",
            },
        }

    def resolve_user(self, authenticated_user, username=None):
        if username is None:
            return authenticated_user

        user = self.users.get(username)

        if user is None:
            raise ValueError(
                f"User '{username}' not found"
            )

        return user


class FakeTransactionService:
    def __init__(self):
        self.transactions = list(FAKE_TRANSACTIONS)

    def get_transactions(self, user):
        return list(self.transactions)

    def filter_transactions(
            self,
            transactions,
            transaction_type=None,
            start_date=None,
            end_date=None,
    ):
        filtered = []

        for transaction in transactions:

            if (
                    transaction_type
                    and transaction.get("Type") != transaction_type
            ):
                continue

            transaction_date = transaction["Date"]

            if start_date and transaction_date < start_date:
                continue

            if end_date and transaction_date > end_date:
                continue

            filtered.append(transaction)

        return filtered

    def get_total(self, transactions):
        return sum(
            float(transaction["Amount"])
            for transaction in transactions
        )

    def get_category_summary(self, transactions):
        summary = {}

        for transaction in transactions:
            category = transaction["Category"]
            amount = float(transaction["Amount"])

            summary[category] = (
                    summary.get(category, 0) + amount
            )

        return summary


def make_session():
    user_service = FakeUserService()

    authenticated_user = user_service.users["Shashwath"]

    transaction_service = FakeTransactionService()

    return {
        "user": authenticated_user,
        "user_service": user_service,
        "transaction_service": transaction_service,
    }


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------

def run_case(case, today):
    """
    Run the actual FinanceAgent against deterministic fake services.

    We keep the real LLM, real tool registry, real tool implementations,
    and real agent loop.
    """

    session = make_session()

    agent = FinanceAgent(
        session=session,
        request_id=f"eval-{uuid.uuid4().hex[:8]}",
    )

    original_call_tool = finance_agent_module.call_tool

    tool_calls = []
    tool_results = []

    def tracked_call_tool(name, session, arguments):
        start = time.perf_counter()

        result = original_call_tool(
            name,
            session,
            arguments,
        )

        duration = time.perf_counter() - start

        tool_calls.append(
            {
                "name": name,
                "arguments": arguments,
                "duration_seconds": round(
                    duration,
                    4,
                ),
            }
        )

        tool_results.append(
            {
                "name": name,
                "result": result,
            }
        )

        return result

    finance_agent_module.call_tool = tracked_call_tool

    llm_calls = 0

    original_create = (
        agent.client.chat.completions.create
    )

    def tracked_create(*args, **kwargs):
        nonlocal llm_calls

        llm_calls += 1

        return original_create(
            *args,
            **kwargs,
        )

    agent.client.chat.completions.create = tracked_create

    start_time = time.perf_counter()

    error = None
    response = None
    updated_history = None
    transaction_draft = None

    try:
        response, updated_history, transaction_draft = (
            agent.respond(case["input"])
        )

    except Exception as exc:
        error = str(exc)

    finally:
        finance_agent_module.call_tool = original_call_tool

    total_latency = (
            time.perf_counter() - start_time
    )

    expected_tool = case["expected_tool"]

    expected_args = resolve_expected_args(
        case.get("expected_args", {}),
        today,
    )

    first_tool = (
        tool_calls[0]["name"]
        if tool_calls
        else None
    )

    first_arguments = (
        tool_calls[0]["arguments"]
        if tool_calls
        else None
    )

    first_tool_correct = (
            first_tool == expected_tool
    )

    first_arguments_correct = (
        arguments_match(
            first_arguments or {},
            expected_args,
        )
    )

    repeated_tools = []

    seen_tools = set()

    for tool_call in tool_calls:
        name = tool_call["name"]

        if name in seen_tools and name not in repeated_tools:
            repeated_tools.append(name)

        seen_tools.add(name)

    tool_errors = [
        result
        for result in tool_results
        if result["result"].get("status") == "error"
    ]

    # Transaction extraction intentionally ends the FinanceAgent loop
    # and returns a transaction draft for the Telegram confirmation flow.
    is_transaction_case = (
            expected_tool == "extract_transaction"
    )

    if is_transaction_case:
        final_response_ok = (
                transaction_draft is not None
                and response is None
        )
    else:
        final_response_ok = (
                response is not None
                and isinstance(response, str)
                and len(response.strip()) > 0
        )

    return {
        "name": case["name"],
        "input": case["input"],
        "expected_tool": expected_tool,
        "expected_args": expected_args,
        "actual_tools": tool_calls,
        "tool_results": tool_results,
        "first_tool": first_tool,
        "first_arguments": first_arguments,
        "first_tool_correct": first_tool_correct,
        "first_arguments_correct": first_arguments_correct,
        "tool_call_count": len(tool_calls),
        "llm_call_count": llm_calls,
        "repeated_tools": repeated_tools,
        "tool_errors": tool_errors,
        "final_response": response,
        "transaction_draft": transaction_draft,
        "final_response_ok": final_response_ok,
        "latency_seconds": round(
            total_latency,
            2,
        ),
        "error": error,
    }


def calculate_summary(results):
    total = len(results)

    if total == 0:
        return {
            "total_cases": 0,
            "first_tool_accuracy": 0,
            "first_argument_accuracy": 0,
            "final_response_success": 0,
            "cases_with_tool_errors": 0,
            "cases_with_repeated_tools": 0,
            "average_tool_calls": 0,
            "average_llm_calls": 0,
            "average_latency_seconds": 0,
        }

    first_tool_correct = sum(
        result["first_tool_correct"]
        for result in results
    )

    first_arguments_correct = sum(
        result["first_arguments_correct"]
        for result in results
    )

    final_response_success = sum(
        result["final_response_ok"]
        for result in results
    )

    cases_with_tool_errors = sum(
        bool(result["tool_errors"])
        for result in results
    )

    cases_with_repeated_tools = sum(
        bool(result["repeated_tools"])
        for result in results
    )

    average_tool_calls = (
            sum(
                result["tool_call_count"]
                for result in results
            )
            / total
    )

    average_llm_calls = (
            sum(
                result["llm_call_count"]
                for result in results
            )
            / total
    )

    average_latency = (
            sum(
                result["latency_seconds"]
                for result in results
            )
            / total
    )

    return {
        "total_cases": total,
        "first_tool_accuracy": round(
            first_tool_correct / total * 100,
            1,
        ),
        "first_argument_accuracy": round(
            first_arguments_correct / total * 100,
            1,
        ),
        "final_response_success": round(
            final_response_success / total * 100,
            1,
        ),
        "cases_with_tool_errors": cases_with_tool_errors,
        "cases_with_repeated_tools": cases_with_repeated_tools,
        "average_tool_calls": round(
            average_tool_calls,
            2,
        ),
        "average_llm_calls": round(
            average_llm_calls,
            2,
        ),
        "average_latency_seconds": round(
            average_latency,
            2,
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cases = load_eval_cases()

    from datetime import date

    today = date.today().isoformat()

    print(
        f"Evaluation date: {today}"
    )

    print(
        f"Cases: {len(cases)}"
    )

    print()

    results = []

    for index, case in enumerate(
            cases,
            start=1,
    ):
        print(
            f"[{index}/{len(cases)}] "
            f"{case['name']} ..."
        )

        result = run_case(
            case,
            today,
        )

        results.append(result)

        passed = (
                result["first_tool_correct"]
                and result["first_arguments_correct"]
                and result["final_response_ok"]
                and not result["tool_errors"]
                and not result["error"]
        )

        if passed:
            print("  PASS")
        else:
            print("  REVIEW")

        print(
            f"  First tool: "
            f"{result['first_tool']}"
        )

        print(
            f"  Tool calls: "
            f"{result['tool_call_count']}"
        )

        print(
            f"  LLM calls: "
            f"{result['llm_call_count']}"
        )

        if result["repeated_tools"]:
            print(
                f"  Repeated: "
                f"{result['repeated_tools']}"
            )

        if result["tool_errors"]:
            print(
                f"  Tool errors: "
                f"{result['tool_errors']}"
            )

        print(
            f"  Final response: "
            f"{result['final_response_ok']}"
        )

        print(
            f"  Latency: "
            f"{result['latency_seconds']}s"
        )

        print()

    summary = calculate_summary(results)

    output = {
        "evaluation_date": today,
        "summary": summary,
        "results": results,
    }

    with open(
            RESULTS_FILE,
            "w",
            encoding="utf-8",
    ) as file:
        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print("=" * 60)
    print("FULL AGENT-LOOP SUMMARY")
    print("=" * 60)

    print(
        f"Cases:                    "
        f"{summary['total_cases']}"
    )

    print(
        f"First-tool accuracy:      "
        f"{summary['first_tool_accuracy']}%"
    )

    print(
        f"First-argument accuracy:  "
        f"{summary['first_argument_accuracy']}%"
    )

    print(
        f"Final response success:   "
        f"{summary['final_response_success']}%"
    )

    print(
        f"Cases with tool errors:   "
        f"{summary['cases_with_tool_errors']}"
    )

    print(
        f"Cases with repeated tools:"
        f" {summary['cases_with_repeated_tools']}"
    )

    print(
        f"Average tool calls:       "
        f"{summary['average_tool_calls']}"
    )

    print(
        f"Average LLM calls:        "
        f"{summary['average_llm_calls']}"
    )

    print(
        f"Average latency:          "
        f"{summary['average_latency_seconds']}s"
    )

    print()

    print(
        f"Results saved to: "
        f"{RESULTS_FILE}"
    )


if __name__ == "__main__":
    main()
