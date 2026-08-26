import re


class ConfConverter:
    @staticmethod
    def conf2json(conf_str: str) -> dict:
        result = {}
        current_section = None

        for line in conf_str.splitlines():
            line = line.strip()
            if not line or line.startswith(('#', ';')):
                continue

            # 1. Ловим секцию [Interface], [Peer]
            section_match = re.match(r'^\[(\w+)]$', line)
            if section_match:
                section_name = section_match.group(1)
                plural_name = f"{section_name}s"

                # Если секция уже была — превращаем/добавляем в массив (Peers)
                if section_name in result:
                    # Переносим первую одиночную секцию в список Peers
                    result[plural_name] = [result.pop(section_name)]
                    current_section = {}
                    result[plural_name].append(current_section)
                elif plural_name in result:
                    current_section = {}
                    result[plural_name].append(current_section)
                else:
                    current_section = {}
                    result[section_name] = current_section
                continue

            # 2. Ловим параметрическую строку Key = Value
            if '=' in line and current_section is not None:
                key, val = map(str.strip, line.split('=', 1))
                current_section[key] = ConfConverter._parse_value(val)

        return result

    @staticmethod
    def json2conf(data: dict) -> str:
        lines = []
        for key, value in data.items():
            # Если ключ оканчивается на 's' и содержит список — это повторяющаяся секция (Peers)
            if isinstance(value, list) and key.endswith('s'):
                section_name = key[:-1]  # "Peers" -> "Peer"
                for item in value:
                    lines.append(f"[{section_name}]")
                    for k, v in item.items():
                        lines.append(f"{k} = {ConfConverter._stringify_value(v)}")
                    lines.append("")  # Пустая строка-разделитель
            # Одиночная секция (Interface)
            elif isinstance(value, dict):
                lines.append(f"[{key}]")
                for k, v in value.items():
                    lines.append(f"{k} = {ConfConverter._stringify_value(v)}")
                lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def _parse_value(val: str):
        """Автоопределение типов: Числа, Массивы байт, Списки IPs"""
        # Парсинг спец-байтов формата <b 010203>
        if val.startswith('<b ') and val.endswith('>'):
            hex_data = val[3:-1].replace(" ", "")
            return list(bytes.fromhex(hex_data))

        # Разбор списков через запятую (например Reserved = 1, 2, 3 или AllowedIPs)
        if ',' in val:
            items = [i.strip() for i in val.split(',')]
            # Если все элементы — цифры, то это массив байт [0, 0, 0]
            if all(i.isdigit() for i in items):
                return [int(i) for i in items]
            return items  # Иначе возвращаем список строк (или оставляем строкой)

        if val.isdigit():
            return int(val)
        return val

    @staticmethod
    def _stringify_value(val) -> str:
        """Обратная конвертация значений в формат .conf"""
        if isinstance(val, list):
            # Массив чисел [0, 0, 0] преобразуем в "0, 0, 0"
            return ", ".join(map(str, val))
        return str(val)
