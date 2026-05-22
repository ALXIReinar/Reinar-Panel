import hashlib

from web.sub.config_dir.config import env


class CryptStrategy:
    @staticmethod
    def md5(signature_string):
        return hashlib.md5(signature_string.encode('utf-8')).hexdigest()

    @staticmethod
    def sha256(signature_string):
        return hashlib.sha256(signature_string.encode('utf-8')).hexdigest()


crypt_strategy = {
    'md5': CryptStrategy.md5,
    'sha256': hashlib.sha256,
}



def payment_meta4signature_string(shp_params: dict):
    sorted_shp_keys = sorted(shp_params.keys()) # Сортируем по ключам. Требование signature_string в Robokassa
    return ':'.join([f'{sort_k}={shp_params[sort_k]}' for sort_k in sorted_shp_keys]) # Shp_csrf_token=fads...Sa:Shp_user_id=1

def create_signature(
        robo_passw: str,
        amount: int | str,
        order_id: int,
        payment_meta_str: str,
):
    signature_string = f"{env.robo_shop_login}:{robo_passw}:{amount}:{order_id}:{payment_meta_str}"
    return signature_string