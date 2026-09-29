import json
import time
from datetime import date, timedelta
from pathlib import Path

from groq import Groq

import agent.tools
from agent.system_prompt import get_system_prompt
from agent.tool_registry import get_tool_definitions
from config import Config

EVAL_CASES_FILE = Path(__file__).parent / "eval_cases.json"
RESULTS_FILE = Path(__file__).parent / "argument_eval_results.json"


def resolve_expected_value(value, today):
    """
    Resolve relative-date placeholders used by eval cases.

    The same `today` value is also passed to the system prompt,
    ensuring the expected arguments and model context use the
    exact same evaluation date.
    """

    if not isinstance(value, str):
        return value

    today_date = date.fromisoformat(today)

    if value == "today":
        return today

    if value == "yesterday":
        return (today_date - timedelta(days=1)).isoformat()

    if value == "this_month_start":
        return today_date.replace(day=1).isoformat()

    if value == "this_month_end":
        if today_date.month == 12:
            next_month = today_date.replace(
                year=today_date.year + 1,
                month=1,
                day=1,
            )
        else:
            next_month = today_date.replace(
                month=today_date.month + 1,
                day=1,
            )

        return (next_month - timedelta(days=1)).isoformat()

    if value == "last_month_start":
        first_this_month = today_date.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)

        return last_month_end.replace(day=1).isoformat()

    if value == "last_month_end":
        first_this_month = today_date.replace(day=1)
        return (first_this_month - timedelta(days=1)).isoformat()

    return value


def resolve_expected_args(expected_args, today):
    """
    Resolve all relative-date placeholders in expected arguments.
    """

    return {
        key: resolve_expected_value(value, today)
        for key, value in expected_args.items()
    }


def arguments_match(actual, expected):
    """
    Compare expected arguments with actual tool arguments.

    Category values are compared case-insensitively because the
    underlying category is semantically the same regardless of casing.
    """

    for key, expected_value in expected.items():
        actual_value = actual.get(key)

        if key == "category":
            if (
                    isinstance(actual_value, str)
                    and isinstance(expected_value, str)
            ):
                if actual_value.strip().lower() != expected_value.strip().lower():
                    return False
                continue

        if actual_value != expected_value:
            return False

    return True


def load_eval_cases():
    with open(EVAL_CASES_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def extract_first_tool_call(response):
    """
    Return the first tool call made by the model.

    Returns:
        {
            "tool_name": str,
            "arguments": dict
        }

    or None if the model did not make a tool call.
    """

    choices = response.choices

    if not choices:
        return None

    message = choices[0].message

    if not message.tool_calls:
        return None

    tool_call = message.tool_calls[0]

    return {
        "tool_name": tool_call.function.name,
        "arguments": json.loads(tool_call.function.arguments),
    }


def run_case(client, model, case, today, tool_definitions):
    """
    Run a single first-tool evaluation case.
    """

    system_prompt = get_system_prompt(today)

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": case["input"],
        },
    ]

    expected_tool = case["expected_tool"]

    expected_args = resolve_expected_args(
        case.get("expected_args", {}),
        today,
    )

    start_time = time.perf_counter()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tool_definitions,
            tool_choice="auto",
        )

        latency = time.perf_counter() - start_time

        tool_call = extract_first_tool_call(response)

        if tool_call is None:
            return {
                "name": case["name"],
                "input": case["input"],
                "expected_tool": expected_tool,
                "expected_args": expected_args,
                "actual_tool": None,
                "actual_args": None,
                "tool_correct": False,
                "arguments_correct": False,
                "overall_correct": False,
                "latency_seconds": round(latency, 2),
                "error": "Model did not make a tool call",
            }

        actual_tool = tool_call["tool_name"]
        actual_args = tool_call["arguments"]

        tool_correct = actual_tool == expected_tool
        arguments_correct = arguments_match(
            actual_args,
            expected_args,
        )

        overall_correct = tool_correct and arguments_correct

        return {
            "name": case["name"],
            "input": case["input"],
            "expected_tool": expected_tool,
            "expected_args": expected_args,
            "actual_tool": actual_tool,
            "actual_args": actual_args,
            "tool_correct": tool_correct,
            "arguments_correct": arguments_correct,
            "overall_correct": overall_correct,
            "latency_seconds": round(latency, 2),
            "error": None,
        }

    except Exception as exc:
        latency = time.perf_counter() - start_time

        return {
            "name": case["name"],
            "input": case["input"],
            "expected_tool": expected_tool,
            "expected_args": expected_args,
            "actual_tool": None,
            "actual_args": None,
            "tool_correct": False,
            "arguments_correct": False,
            "overall_correct": False,
            "latency_seconds": round(latency, 2),
            "error": str(exc),
        }


def calculate_summary(results):
    total = len(results)

    if total == 0:
        return {
            "total_cases": 0,
            "tool_accuracy": 0,
            "argument_accuracy": 0,
            "overall_accuracy": 0,
            "average_latency_seconds": 0,
        }

    tool_correct = sum(
        result["tool_correct"]
        for result in results
    )

    arguments_correct = sum(
        result["arguments_correct"]
        for result in results
    )

    overall_correct = sum(
        result["overall_correct"]
        for result in results
    )

    total_latency = sum(
        result["latency_seconds"]
        for result in results
    )

    return {
        "total_cases": total,
        "tool_accuracy": round(
            tool_correct / total * 100,
            1,
        ),
        "argument_accuracy": round(
            arguments_correct / total * 100,
            1,
        ),
        "overall_accuracy": round(
            overall_correct / total * 100,
            1,
        ),
        "average_latency_seconds": round(
            total_latency / total,
            2,
        ),
    }


def main():
    cases = load_eval_cases()

    client = Groq(api_key=Config.GROQ_API_KEY)
    model = "openai/gpt-oss-120b"

    # Freeze the evaluation date for this entire run.
    # The exact same value is passed to:
    #   1. the system prompt
    #   2. expected argument resolution
    today = date.today().isoformat()

    tool_definitions = get_tool_definitions()

    print(f"Evaluation date: {today}")
    print(f"Model: {model}")
    print(f"Cases: {len(cases)}")
    print()

    results = []

    for index, case in enumerate(cases, start=1):
        print(
            f"[{index}/{len(cases)}] "
            f"{case['name']} ..."
        )

        result = run_case(
            client=client,
            model=model,
            case=case,
            today=today,
            tool_definitions=tool_definitions,
        )

        results.append(result)

        if result["overall_correct"]:
            print("  PASS")
        else:
            print("  FAIL")

            print(
                f"  Expected tool: "
                f"{result['expected_tool']}"
            )

            print(
                f"  Actual tool:   "
                f"{result['actual_tool']}"
            )

            print(
                f"  Expected args: "
                f"{result['expected_args']}"
            )

            print(
                f"  Actual args:   "
                f"{result['actual_args']}"
            )

            if result["error"]:
                print(
                    f"  Error: "
                    f"{result['error']}"
                )

        print(
            f"  Latency: "
            f"{result['latency_seconds']}s"
        )
        print()

    summary = calculate_summary(results)

    output = {
        "evaluation_date": today,
        "model": model,
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
    print("SUMMARY")
    print("=" * 60)

    print(
        f"Total cases:        "
        f"{summary['total_cases']}"
    )

    print(
        f"Tool accuracy:      "
        f"{summary['tool_accuracy']}%"
    )

    print(
        f"Argument accuracy:  "
        f"{summary['argument_accuracy']}%"
    )

    print(
        f"Overall accuracy:   "
        f"{summary['overall_accuracy']}%"
    )

    print(
        f"Average latency:    "
        f"{summary['average_latency_seconds']}s"
    )

    print()
    print(
        f"Results saved to: "
        f"{RESULTS_FILE}"
    )


if __name__ == "__main__":
    main()
