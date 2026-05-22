from dataclasses import dataclass


@dataclass
class RobokassaUrls:
    create_payment = 'https://auth.robokassa.ru/Merchant/Index.aspx' # Пользователь перейдёт на страницу робокассы для оплаты


@dataclass
class Constants:

    @staticmethod
    def payment_robo_lock(csrf_token: str):
        return f'pay_lock:robo:{csrf_token}'