import random

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config_dir.config import env
from bot.core.utils.schemas import SubOfferSchema


def main_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='💎 Купить/Продлить')],
        [KeyboardButton(text='👤 Личный кабинет')],
        [KeyboardButton(text='🔗 Наши ссылки')],
    ])
    return kb


def subs_intro_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text='🔄 Продлить', callback_data='subs-upd-intro')
    kb.button(text='➕ Купить новую', callback_data=f'subs-shop')
    kb.button(text='⬅️ Назад', callback_data=f'back')
    return kb.as_markup()


def fallback_user_subs():
    kb = InlineKeyboardBuilder()
    kb.button(text='➕ Купить подписку', callback_data='subs-shop')
    return kb.as_markup()


def user_subs_slider(cur_user_sub_idx: int, total_subs: int):
    prev_idx = cur_user_sub_idx - 1 if cur_user_sub_idx != 0 else total_subs - 1
    next_idx = cur_user_sub_idx + 1 if cur_user_sub_idx < total_subs - 1 else 0

    kb = InlineKeyboardBuilder()
    kb.button(text='<', callback_data=f'subs-user-pagen_{prev_idx}')
    kb.button(text=f'{cur_user_sub_idx + 1}/{total_subs}', callback_data=f'None')
    kb.button(text='>', callback_data=f'subs-user-pagen_{next_idx}')
    kb.button(text='🔄 Продлить', callback_data=f'subs-user-upd_{cur_user_sub_idx}')
    kb.adjust(3, 1)
    return kb.as_markup()

def shop_subs_slider(cur_sub_plan_idx: int, total_subs: int):
    prev_idx = cur_sub_plan_idx - 1 if cur_sub_plan_idx != 0 else total_subs - 1
    next_idx = cur_sub_plan_idx + 1 if cur_sub_plan_idx < total_subs - 1 else 0

    kb = InlineKeyboardBuilder()
    kb.button(text='<', callback_data=f'subs-shop-pagen_{prev_idx}')
    kb.button(text=f'{cur_sub_plan_idx + 1}/{total_subs}', callback_data=f'None')
    kb.button(text='>', callback_data=f'subs-shop-pagen_{next_idx}')
    kb.button(text='➕ Купить', callback_data=f'subs-shop-upd_{cur_sub_plan_idx}')
    kb.adjust(3, 1)
    return kb.as_markup()



def user_sub_plan_offers(user_sub_idx, costs_days_list):
    """
    Копия shop_sub_plan_offers. НО важное отличие - **call_data** ключи
    """
    kb = InlineKeyboardBuilder()

    for offer_idx, item in enumerate(costs_days_list):
        offer = SubOfferSchema.fast_create(item)
        text = env.message_templates.render('message_subscriptions_offers_extent', offer)
        kb.button(text=text.strip(), callback_data=f'subs-user-offer_{user_sub_idx}_{offer_idx}')

    kb.button(text='⬅️ Назад', callback_data=f'subs-user-pagen_{user_sub_idx}')
    return kb.as_markup()

def shop_sub_plan_offers(sub_plan_idx, costs_days_list):
    """
    Копия user_sub_plan_offers. НО важное отличие - **call_data** ключи
    """
    kb = InlineKeyboardBuilder()

    for offer_idx, item in enumerate(costs_days_list):
        offer = SubOfferSchema.fast_create(item)
        text = env.message_templates.render('message_subscriptions_offers_extent', offer)
        kb.button(text=text.strip(), callback_data=f'subs-shop-offer_{sub_plan_idx}_{offer_idx}')

    kb.button(text='⬅️ Назад', callback_data=f'subs-shop-pagen_{sub_plan_idx}')
    return kb.as_markup()


def payment_kb(pay_link: str):
    kb = InlineKeyboardBuilder()
    kb.button(text='🌐 Оплатить', url=pay_link)
    kb.button(text='🏘 Главное меню', callback_data='back')
    return kb.as_markup()