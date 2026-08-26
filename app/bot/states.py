from aiogram.fsm.state import State, StatesGroup


class DealWonForm(StatesGroup):
    product = State()
    amount = State()
    quantity = State()


class DealLostForm(StatesGroup):
    reason = State()

