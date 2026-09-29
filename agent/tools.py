from agent.tool_registry import llm_tool


@llm_tool()
def get_total_expenses(session, start_date: str | None = None, end_date: str | None = None,
                       username: str | None = None):
    """
    Calculate the total amount of expenses for a user.

    Use this tool whenever the user asks about:
    - total spending
    - total expenses
    - how much they spent
    - spending over a specific period
    - spending this month
    - spending last month
    - spending between two dates

    If a username is provided, calculate expenses for that user.
    If no username is provided, use the authenticated user's data.

    :param start_date: Optional start date, inclusive, in YYYY-MM-DD format.
    :param end_date: Optional end date, inclusive, in YYYY-MM-DD format.
    :param username: Optional username to query. If omitted, use the authenticated user.
    """

    user_service = session["user_service"]
    transaction_service = session["transaction_service"]

    user = user_service.resolve_user(session["user"], username)
    transactions = transaction_service.get_transactions(user)
    expenses = transaction_service.filter_transactions(transactions, transaction_type="Expense",
                                                       start_date=start_date, end_date=end_date)
    total = transaction_service.get_total(expenses)
    return {
        "status": "success",
        "type": "total_expenses",
        "username": user["username"],
        "start_date": start_date,
        "end_date": end_date,
        "total": total,
    }


@llm_tool()
def get_category_summary(session, start_date: str | None = None, end_date: str | None = None,
                         category: str | None = None, username: str | None = None):
    """
    Summarize a user's expenses by category.

    Use this tool when the user asks:
    - where they spent their money
    - how much they spent in each category
    - for a breakdown of their expenses by category
    - how much they spent on a specific category

    Only transactions with Type = Expense are included.

    If a username is provided, calculate the summary for that user.
    If no username is provided, use the authenticated user's data.

    :param start_date: Optional start date, inclusive, in YYYY-MM-DD format.
    :param end_date: Optional end date, inclusive, in YYYY-MM-DD format.
    :param category: Optional expense category such as Food, Travel, or Shopping.
    :param username: Optional username to query. If omitted, use the authenticated user.
    """

    user_service = session["user_service"]
    transaction_service = session["transaction_service"]
    user = user_service.resolve_user(session["user"], username)
    transactions = transaction_service.get_transactions(user)
    expenses = transaction_service.filter_transactions(transactions, transaction_type="Expense", start_date=start_date,
                                                       end_date=end_date)
    if category:
        expenses = [transaction for transaction in expenses if transaction["Category"].lower() == category.lower()]
    summary = transaction_service.get_category_summary(expenses)
    total = transaction_service.get_total(expenses)

    return {
        "status": "success",
        "type": "category_summary",
        "username": user["username"],
        "start_date": start_date,
        "end_date": end_date,
        "category": category,
        "summary": summary,
        "total": total,
    }


@llm_tool()
def compare_expenses(session, period_1_start: str, period_1_end: str, period_2_start: str, period_2_end: str,
                     username: str | None = None, ):
    """
    Compare total expenses between two time periods for a user.

    Use this tool when the user asks to compare spending or expenses
    between two different time periods.

    The first requested period is period 1.
    The second requested period is period 2.

    Only transactions with Type = Expense are included.

    If a username is provided, calculate the comparison for that user.
    If no username is provided, use the authenticated user's data.

    :param period_1_start: Start date of the first period, inclusive, in YYYY-MM-DD format.
    :param period_1_end: End date of the first period, inclusive, in YYYY-MM-DD format.
    :param period_2_start: Start date of the second period, inclusive, in YYYY-MM-DD format.
    :param period_2_end: End date of the second period, inclusive, in YYYY-MM-DD format.
    :param username: Optional username to query. If omitted, use the authenticated user.
    """

    user_service = session["user_service"]
    transaction_service = session["transaction_service"]
    user = user_service.resolve_user(session["user"], username)
    transactions = transaction_service.get_transactions(user)
    period_1_transactions = transaction_service.filter_transactions(transactions, transaction_type="Expense",
                                                                    start_date=period_1_start, end_date=period_1_end)
    period_2_transactions = transaction_service.filter_transactions(transactions, transaction_type="Expense",
                                                                    start_date=period_2_start, end_date=period_2_end)
    period_1_total = transaction_service.get_total(period_1_transactions)
    period_2_total = transaction_service.get_total(period_2_transactions)
    difference = period_2_total - period_1_total
    if period_1_total == 0:
        percentage_change = None
    else:
        percentage_change = (difference / period_1_total) * 100

    return {
        "status": "success",
        "type": "expense_comparison",
        "username": user["username"],
        "period_1": {
            "start_date": period_1_start,
            "end_date": period_1_end,
            "total": period_1_total,
        },
        "period_2": {
            "start_date": period_2_start,
            "end_date": period_2_end,
            "total": period_2_total,
        },
        "difference": difference,
        "percentage_change": percentage_change,
    }


@llm_tool()
def compare_category_expenses(session, period_1_start: str, period_1_end: str, period_2_start: str, period_2_end: str,
                              category: str | None = None, username: str | None = None):
    """
    Compare category-wise expenses between two time periods for a user.

    Use this tool when the user asks to compare spending between
    two different time periods, either:
    - across all expense categories, or
    - for a specific expense category.

    The first requested period is period 1.
    The second requested period is period 2.

    Only transactions with Type = Expense are included.

    If a category is provided, only expenses belonging to that
    category are included in the comparison.

    If a username is provided, calculate the comparison for that user.
    If no username is provided, use the authenticated user's data.

    :param period_1_start: Start date of the first period, inclusive,
                           in YYYY-MM-DD format.
    :param period_1_end: End date of the first period, inclusive,
                         in YYYY-MM-DD format.
    :param period_2_start: Start date of the second period, inclusive,
                           in YYYY-MM-DD format.
    :param period_2_end: End date of the second period, inclusive,
                         in YYYY-MM-DD format.
    :param category: Optional expense category such as Food, Travel,
                     or Shopping. If omitted, compare all categories.
    :param username: Optional username to query. If omitted, use
                     the authenticated user.
    """

    user_service = session["user_service"]
    transaction_service = session["transaction_service"]
    user = user_service.resolve_user(session["user"], username)
    transactions = transaction_service.get_transactions(user)
    period_1_transactions = transaction_service.filter_transactions(transactions, transaction_type="Expense",
                                                                    start_date=period_1_start, end_date=period_1_end)

    period_2_transactions = transaction_service.filter_transactions(transactions, transaction_type="Expense",
                                                                    start_date=period_2_start, end_date=period_2_end)

    if category:
        period_1_transactions = [transaction for transaction in period_1_transactions
                                 if transaction.get("Category", "").lower() == category.lower()]

        period_2_transactions = [transaction for transaction in period_2_transactions
                                 if transaction.get("Category", "").lower() == category.lower()]

    period_1_summary = transaction_service.get_category_summary(period_1_transactions)
    period_2_summary = transaction_service.get_category_summary(period_2_transactions)
    period_1_total = transaction_service.get_total(period_1_transactions)
    period_2_total = transaction_service.get_total(period_2_transactions)
    categories = set(period_1_summary) | set(period_2_summary)

    category_comparison = {}

    for expense_category in categories:
        amount_1 = period_1_summary.get(expense_category, 0)
        amount_2 = period_2_summary.get(expense_category, 0)
        difference = amount_2 - amount_1
        if amount_1 == 0:
            percentage_change = None
        else:
            percentage_change = (difference / amount_1) * 100

        category_comparison[expense_category] = {
            "period_1": amount_1,
            "period_2": amount_2,
            "difference": difference,
            "percentage_change": percentage_change,
        }

    return {
        "status": "success",
        "type": "category_expense_comparison",
        "username": user["username"],
        "category": category,
        "period_1": {
            "start_date": period_1_start,
            "end_date": period_1_end,
            "total": period_1_total,
            "categories": period_1_summary,
        },
        "period_2": {
            "start_date": period_2_start,
            "end_date": period_2_end,
            "total": period_2_total,
            "categories": period_2_summary,
        },
        "category_comparison": category_comparison,
    }


@llm_tool()
def extract_transaction(session, transaction_type: str, amount: float, reason: str | None = None,
                        category: str | None = None, from_account: str | None = None, to_account: str | None = None,
                        transaction_date: str | None = None):
    """
    Extract a transaction draft from the user's message.

    This tool ONLY extracts transaction information and creates a draft.
    It DOES NOT save, record, submit, or write anything to Google Sheets.

    :transaction_type: Transaction type: Expense, Income, Transfer, or Investment.
    :amount: Transaction amount in INR.
    :reason: Short description or reason for the transaction.
    :category: Category explicitly provided by the user, otherwise null.
    :from_account: Source account explicitly provided by the user, otherwise null.
    :to_account: Destination account explicitly provided by the user, otherwise null.
    :transaction_date: Transaction date in YYYY-MM-DD format if explicitly provided or implied by the user, otherwise null.
    """

    return {
        "status": "success",
        "transaction": {
            "type": transaction_type,
            "amount": amount,
            "reason": reason,
            "category": category,
            "from_account": from_account,
            "to_account": to_account,
            "transaction_date": transaction_date,
        },
    }
