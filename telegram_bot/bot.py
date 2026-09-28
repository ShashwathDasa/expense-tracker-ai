import time
from datetime import date
from uuid import uuid4

from telegram import Update
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from agent.finance_agent import FinanceAgent
from config import Config
from conversation.store import ConversationStore
from telegram_bot.keyboards import create_option_keyboard, create_confirmation_keyboard
from transaction.state import PendingTransactionStore
from utils.logger import logger


class TelegramBot:
    def __init__(self, user_service, transaction_service):
        self.user_service = user_service
        self.transaction_service = transaction_service
        self.conversation_store = ConversationStore()
        self.pending_transactions = PendingTransactionStore()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        user = self.user_service.get_user_by_chat_id(chat_id)
        if user is None:
            await update.message.reply_text("You are not authorized to use this bot.")
            return

        await update.message.reply_text(f"Hi {user['username']}!")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        message = update.message.text
        user = self.user_service.get_user_by_chat_id(chat_id)
        if user is None:
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        request_id = uuid4().hex[:8]
        request_start = time.perf_counter()
        logger.info("Request started request_id=%s user=%s", request_id, user["username"])
        # -----------------------------------
        # HANDLE PENDING TRANSACTION INPUT
        # -----------------------------------

        transaction = self.pending_transactions.get(chat_id)
        if transaction:
            waiting_for = transaction.get("waiting_for")
            if waiting_for == "reason":
                self.pending_transactions.update(chat_id, reason=message, waiting_for=None)
                transaction = self.pending_transactions.get(chat_id)
                await self.handle_transaction_draft(update, transaction)
                return

        # -----------------------------------
        # NORMAL LLM FLOW
        # -----------------------------------

        session = {
            "user": user,
            "user_service": self.user_service,
            "transaction_service": self.transaction_service,
        }

        processing_message = await update.message.reply_text("⏳ Processing...")
        history = self.conversation_store.get_history(chat_id)
        agent = FinanceAgent(session, request_id)
        response, updated_history, transaction_draft = agent.respond(message, history)
        self.conversation_store.save_history(chat_id, updated_history)
        await processing_message.delete()
        if transaction_draft:
            self.pending_transactions.create(chat_id, transaction_draft)
            await self.handle_transaction_draft(update, transaction_draft)
            return

        await update.message.reply_text(response)
        self.log_request_completed(user, request_id, request_start)

    def log_request_completed(self, user, request_id, request_start, status="success"):
        duration = time.perf_counter() - request_start
        logger.info("Request completed request_id=%s user=%s duration=%.2fs status=%s", request_id, user["username"],
                    duration, status)

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error("Unhandled exception while processing update: %s", context.error, exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Sorry, something went wrong while processing your request.")

    async def handle_transaction_draft(self, update, transaction):
        chat_id = update.effective_chat.id
        transaction_type = transaction.get("type")

        # -----------------------------------
        # EXPENSE
        # -----------------------------------

        if transaction_type == "Expense":
            # Category
            if not transaction.get("category"):
                user = self.user_service.get_user_by_chat_id(chat_id)
                categories = self.transaction_service.get_most_used_categories_for_user(user)
                keyboard = create_option_keyboard(categories, callback_prefix="category")
                if update.callback_query:
                    await update.callback_query.edit_message_text("Which category?", reply_markup=keyboard)
                else:
                    await update.message.reply_text("Which category?", reply_markup=keyboard)
                return

            # From account
            if not transaction.get("from_account"):
                user = self.user_service.get_user_by_chat_id(chat_id)
                accounts = self.transaction_service.get_most_used_accounts_for_user(user)
                keyboard = create_option_keyboard(accounts, callback_prefix="account")
                if update.callback_query:
                    await update.callback_query.edit_message_text("Which account did you pay from?",
                                                                  reply_markup=keyboard)
                else:
                    await update.message.reply_text("Which account did you pay from?", reply_markup=keyboard)
                return

        # -----------------------------------
        # TRANSFER
        # -----------------------------------

        if transaction_type == "Transfer":
            # From account
            if not transaction.get("from_account"):
                user = self.user_service.get_user_by_chat_id(chat_id)
                accounts = self.transaction_service.get_most_used_accounts_for_user(user)
                keyboard = create_option_keyboard(accounts, callback_prefix="account")
                if update.callback_query:
                    await update.callback_query.edit_message_text("Which account are you transferring from?",
                                                                  reply_markup=keyboard)
                else:
                    await update.message.reply_text("Which account are you transferring from?", reply_markup=keyboard)
                return

            # To account
            if not transaction.get("to_account"):
                user = self.user_service.get_user_by_chat_id(chat_id)
                accounts = self.transaction_service.get_most_used_accounts_for_user(user)
                keyboard = create_option_keyboard(accounts, callback_prefix="to_account")
                if update.callback_query:
                    await update.callback_query.edit_message_text("Which account are you transferring to?",
                                                                  reply_markup=keyboard)
                else:
                    await update.message.reply_text("Which account are you transferring to?", reply_markup=keyboard)
                return

        # -----------------------------------
        # REASON
        # -----------------------------------

        if not transaction.get("reason"):
            self.pending_transactions.update(chat_id, waiting_for="reason")
            if update.callback_query:
                await update.callback_query.edit_message_text("What was this transaction for?")
            else:
                await update.message.reply_text("What was this transaction for?")
            return

        # -----------------------------------
        # DATE
        # -----------------------------------

        if not transaction.get("transaction_date"):
            transaction["transaction_date"] = date.today().isoformat()
            self.pending_transactions.update(chat_id, transaction_date=transaction["transaction_date"])

        # -----------------------------------
        # CONFIRMATION
        # -----------------------------------

        await self.show_transaction_confirmation(update, transaction)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat_id
        callback_data = query.data
        prefix, value = callback_data.split(":", 1)
        transaction = self.pending_transactions.get(chat_id)
        if transaction is None:
            await query.edit_message_text("This transaction session has expired.")
            return

        # -----------------------------------
        # CATEGORY SELECTION
        # -----------------------------------

        if prefix == "category":
            self.pending_transactions.update(chat_id, category=value)
            transaction = self.pending_transactions.get(chat_id)
            # Category selection is a callback,
            # so handle the next missing field.
            await self.handle_transaction_draft(update, transaction)
            return

        # -----------------------------------
        # FROM ACCOUNT SELECTION
        # -----------------------------------

        if prefix == "account":
            self.pending_transactions.update(chat_id, from_account=value)
            transaction = self.pending_transactions.get(chat_id)
            await self.handle_transaction_draft(update, transaction)
            return

        # -----------------------------------
        # TO ACCOUNT SELECTION
        # -----------------------------------

        if prefix == "to_account":
            self.pending_transactions.update(chat_id, to_account=value)
            transaction = self.pending_transactions.get(chat_id)
            await self.handle_transaction_draft(update, transaction)
            return

        # -----------------------------------
        # CONFIRMATION
        # -----------------------------------

        if prefix == "confirm":
            # Cancel
            if value == "no":
                self.pending_transactions.clear(chat_id)
                await query.edit_message_text("Transaction cancelled.")
                return

            # Confirm
            if value == "yes":
                transaction = self.pending_transactions.get(chat_id)
                if transaction is None:
                    await query.edit_message_text("This transaction session has expired.")
                    return
                user = self.user_service.get_user_by_chat_id(chat_id)
                if user is None:
                    await query.edit_message_text("You are not authorized to perform this action.")
                    return

                try:
                    self.transaction_service.add_transaction(user, transaction)
                    self.pending_transactions.clear(chat_id)
                    await query.edit_message_text("✅ Transaction saved.")
                except Exception as error:
                    await query.edit_message_text(f"❌ Could not save transaction:\n{error}")
                return

    async def show_transaction_confirmation(self, update, transaction):
        transaction_date = transaction.get("transaction_date")
        if transaction_date:
            display_date = date.fromisoformat(transaction_date).strftime("%d-%b-%Y")
        else:
            display_date = date.today().strftime("%d-%b-%Y")

        message = (
            "Transaction draft:\n\n"
            f"Date: {display_date}\n"
            f"Type: {transaction['type']}\n"
            f"Amount: ₹{transaction['amount']:.2f}\n"
        )

        if transaction.get("category"):
            message += f"Category: {transaction['category']}\n"
        if transaction.get("from_account"):
            message += f"From account: {transaction['from_account']}\n"
        if transaction.get("to_account"):
            message += f"To account: {transaction['to_account']}\n"
        if transaction.get("reason"):
            message += f"Reason: {transaction['reason']}\n"
        message += "\nSave this transaction?"
        keyboard = create_confirmation_keyboard()
        if update.callback_query:
            await update.callback_query.edit_message_text(message, reply_markup=keyboard)
        else:
            await update.message.reply_text(message, reply_markup=keyboard)

    def run(self):
        application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CallbackQueryHandler(self.handle_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        application.add_error_handler(self.error_handler)
        application.run_polling()
