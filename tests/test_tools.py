from agent.tools import get_total_expenses, get_category_summary, compare_expenses, compare_category_expenses, \
    extract_transaction


class FakeUserService:
    def resolve_user(self, authenticated_user, username):
        return {"username": username or authenticated_user["username"]}


class FakeTransactionService:
    def get_transactions(self, user):
        return [
            {
                "Type": "Expense",
                "Amount": 500,
                "Date": "2026-09-10",
            },
            {
                "Type": "Expense",
                "Amount": 300,
                "Date": "2026-09-15",
            },
            {
                "Type": "Income",
                "Amount": 5000,
                "Date": "2026-09-15",
            },
        ]

    def filter_transactions(self, transactions, transaction_type=None, start_date=None, end_date=None):
        result = transactions
        if transaction_type:
            result = [t for t in result if t["Type"] == transaction_type]
        if start_date:
            result = [t for t in result if t["Date"] >= start_date]
        if end_date:
            result = [t for t in result if t["Date"] <= end_date]
        return result

    def get_total(self, transactions):
        return sum(t["Amount"] for t in transactions)

    def get_category_summary(self, transactions):
        summary = {}
        for transaction in transactions:
            category = transaction["Category"]
            amount = transaction["Amount"]
            summary[category] = summary.get(category, 0) + amount
        return summary


def make_session():
    return {
        "user": {"username": "Shashwath"},
        "user_service": FakeUserService(),
        "transaction_service": FakeTransactionService(),
    }


def test_get_total_expenses():
    session = make_session()
    result = get_total_expenses(session)
    assert result["status"] == "success"
    assert result["type"] == "total_expenses"
    assert result["username"] == "Shashwath"
    assert result["total"] == 800


def test_get_total_expenses_ignores_income():
    session = make_session()
    result = get_total_expenses(session)
    assert result["total"] == 800


def test_get_total_expenses_with_date_range():
    session = make_session()
    result = get_total_expenses(session, start_date="2026-09-15", end_date="2026-09-15")
    assert result["total"] == 300


def test_get_total_expenses_for_zero_expenses():
    session = make_session()
    session["transaction_service"].get_transactions = lambda user: [
        {
            "Type": "Income",
            "Amount": 5000,
            "Date": "2026-09-15",
        }
    ]
    result = get_total_expenses(session)
    assert result["total"] == 0


def test_get_category_summary():
    session = make_session()
    session["transaction_service"].get_transactions = lambda user: [
        {
            "Type": "Expense",
            "Category": "Food",
            "Amount": 500,
            "Date": "2026-09-10",
        },
        {
            "Type": "Expense",
            "Category": "Food",
            "Amount": 300,
            "Date": "2026-09-15",
        },
        {
            "Type": "Expense",
            "Category": "Travel",
            "Amount": 1000,
            "Date": "2026-09-15",
        },
    ]

    result = get_category_summary(session)
    assert result["status"] == "success"
    assert result["total"] == 1800
    assert result["summary"]["Food"] == 800
    assert result["summary"]["Travel"] == 1000


def test_get_category_summary_for_specific_category():
    session = make_session()
    session["transaction_service"].get_transactions = lambda user: [
        {
            "Type": "Expense",
            "Category": "Food",
            "Amount": 500,
            "Date": "2026-09-10",
        },
        {
            "Type": "Expense",
            "Category": "Travel",
            "Amount": 1000,
            "Date": "2026-09-15",
        },
    ]

    result = get_category_summary(
        session,
        category="Food",
    )

    assert result["total"] == 500
    assert result["summary"]["Food"] == 500
    assert "Travel" not in result["summary"]


def test_get_category_summary_is_case_insensitive():
    session = make_session()
    session["transaction_service"].get_transactions = lambda user: [
        {
            "Type": "Expense",
            "Category": "Food",
            "Amount": 500,
            "Date": "2026-09-10",
        }
    ]

    result = get_category_summary(session, category="food")
    assert result["total"] == 500


def test_compare_expenses():
    session = make_session()

    session["transaction_service"].get_transactions = lambda user: [
        {
            "Type": "Expense",
            "Amount": 1000,
            "Date": "2026-09-01",
        },
        {
            "Type": "Expense",
            "Amount": 1500,
            "Date": "2026-09-15",
        },
    ]

    result = compare_expenses(session, period_1_start="2026-09-01", period_1_end="2026-09-10",
                              period_2_start="2026-09-11", period_2_end="2026-09-30")

    assert result["period_1"]["total"] == 1000
    assert result["period_2"]["total"] == 1500
    assert result["difference"] == 500
    assert result["percentage_change"] == 50


def test_compare_expenses_decrease():
    session = make_session()
    session["transaction_service"].get_transactions = lambda user: [
        {
            "Type": "Expense",
            "Amount": 2000,
            "Date": "2026-09-05",
        },
        {
            "Type": "Expense",
            "Amount": 1500,
            "Date": "2026-09-20",
        },
    ]

    result = compare_expenses(session, period_1_start="2026-09-01", period_1_end="2026-09-10",
                              period_2_start="2026-09-11", period_2_end="2026-09-30")

    assert result["difference"] == -500
    assert result["percentage_change"] == -25


def test_compare_expenses_with_zero_previous_period():
    session = make_session()

    session["transaction_service"].get_transactions = lambda user: [
        {
            "Type": "Expense",
            "Amount": 1500,
            "Date": "2026-09-20",
        },
    ]

    result = compare_expenses(session, period_1_start="2026-09-01", period_1_end="2026-09-10",
                              period_2_start="2026-09-11", period_2_end="2026-09-30")

    assert result["period_1"]["total"] == 0
    assert result["period_2"]["total"] == 1500
    assert result["difference"] == 1500
    assert result["percentage_change"] is None


def test_compare_category_expenses():
    session = make_session()
    session["transaction_service"].get_transactions = lambda user: [
        {
            "Type": "Expense",
            "Category": "Food",
            "Amount": 1000,
            "Date": "2026-09-05",
        },
        {
            "Type": "Expense",
            "Category": "Travel",
            "Amount": 500,
            "Date": "2026-09-05",
        },
        {
            "Type": "Expense",
            "Category": "Food",
            "Amount": 1500,
            "Date": "2026-09-20",
        },
        {
            "Type": "Expense",
            "Category": "Travel",
            "Amount": 250,
            "Date": "2026-09-20",
        },
    ]

    result = compare_category_expenses(session, period_1_start="2026-09-01", period_1_end="2026-09-10",
                                       period_2_start="2026-09-11", period_2_end="2026-09-30")

    assert result["category_comparison"]["Food"]["period_1"] == 1000
    assert result["category_comparison"]["Food"]["period_2"] == 1500
    assert result["category_comparison"]["Food"]["difference"] == 500
    assert result["category_comparison"]["Food"]["percentage_change"] == 50

    assert result["category_comparison"]["Travel"]["period_1"] == 500
    assert result["category_comparison"]["Travel"]["period_2"] == 250
    assert result["category_comparison"]["Travel"]["difference"] == -250
    assert result["category_comparison"]["Travel"]["percentage_change"] == -50

    result = compare_category_expenses(session, period_1_start="2026-09-01", period_1_end="2026-09-10",
                                       period_2_start="2026-09-11", period_2_end="2026-09-30", category="Food")

    assert result["category"] == "Food"
    assert result["period_1"]["total"] == 1000
    assert result["period_2"]["total"] == 1500
    assert result["period_1"]["categories"] == {"Food": 1000}
    assert result["period_2"]["categories"] == {"Food": 1500}
    assert result["category_comparison"]["Food"]["period_1"] == 1000
    assert result["category_comparison"]["Food"]["period_2"] == 1500
    assert result["category_comparison"]["Food"]["difference"] == 500
    assert result["category_comparison"]["Food"]["percentage_change"] == 50
    assert "Travel" not in result["category_comparison"]


def test_compare_category_expenses_new_category():
    session = make_session()
    session["transaction_service"].get_transactions = lambda user: [
        {
            "Type": "Expense",
            "Category": "Food",
            "Amount": 1000,
            "Date": "2026-09-05",
        },
        {
            "Type": "Expense",
            "Category": "Shopping",
            "Amount": 750,
            "Date": "2026-09-20",
        },
    ]

    result = compare_category_expenses(session, period_1_start="2026-09-01", period_1_end="2026-09-10",
                                       period_2_start="2026-09-11", period_2_end="2026-09-30")

    shopping = result["category_comparison"]["Shopping"]

    assert shopping["period_1"] == 0
    assert shopping["period_2"] == 750
    assert shopping["difference"] == 750
    assert shopping["percentage_change"] is None


def test_compare_category_expenses_removed_category():
    session = make_session()
    session["transaction_service"].get_transactions = lambda user: [
        {
            "Type": "Expense",
            "Category": "Travel",
            "Amount": 1000,
            "Date": "2026-09-05",
        },
        {
            "Type": "Expense",
            "Category": "Food",
            "Amount": 500,
            "Date": "2026-09-20",
        },
    ]

    result = compare_category_expenses(session, period_1_start="2026-09-01", period_1_end="2026-09-10",
                                       period_2_start="2026-09-11", period_2_end="2026-09-30")
    travel = result["category_comparison"]["Travel"]
    assert travel["period_1"] == 1000
    assert travel["period_2"] == 0
    assert travel["difference"] == -1000
    assert travel["percentage_change"] == -100


def test_extract_transaction_creates_draft():
    session = make_session()
    result = extract_transaction(session, transaction_type="Expense", amount=500, reason="Dinner", category="Food",
                                 from_account="Kotak", transaction_date="2026-09-28")

    assert result["status"] == "success"
    transaction = result["transaction"]
    assert transaction["type"] == "Expense"
    assert transaction["amount"] == 500
    assert transaction["reason"] == "Dinner"
    assert transaction["category"] == "Food"
    assert transaction["from_account"] == "Kotak"
    assert transaction["transaction_date"] == "2026-09-28"


def test_extract_transaction_allows_missing_optional_fields():
    session = make_session()
    result = extract_transaction(session, transaction_type="Expense", amount=500)
    transaction = result["transaction"]
    assert transaction["type"] == "Expense"
    assert transaction["amount"] == 500
    assert transaction["reason"] is None
    assert transaction["category"] is None
    assert transaction["from_account"] is None
    assert transaction["to_account"] is None
    assert transaction["transaction_date"] is None
