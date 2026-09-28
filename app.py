from sheets.client import GoogleSheetsClient
from sheets.users import UserService
from sheets.transactions import TransactionService
from telegram_bot.bot import TelegramBot


def create_bot():
    sheets_client = GoogleSheetsClient()
    user_service = UserService(sheets_client)
    transaction_service = TransactionService(sheets_client)
    return TelegramBot(user_service, transaction_service)


def main():
    bot = create_bot()
    bot.run()


if __name__ == "__main__":
    main()
