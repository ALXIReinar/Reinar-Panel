import re
from pathlib import Path

file_path = Path('web/tests/integrate/test_sub_plans.py')
content = file_path.read_text(encoding='utf-8')

# 1. Замена "id": в offers на "offer_id":
content = re.sub(
    r'"id":\s*offer_id',
    r'"offer_id": offer_id',
    content
)

# 2. Замена get_data["offers"] на get_data["plan"]["offers"]
content = content.replace(
    'offers = get_data["offers"]',
    'offers = get_data["plan"]["offers"]'
)

# 3. Замена get_data["vnodes"] на get_data["plan"]["vnodes"]
content = content.replace(
    'vnodes = get_data["vnodes"]',
    'vnodes = get_data["plan"]["vnodes"]'
)

# 4. Замена assert "vnodes" in data на assert "vnodes" in data["plan"]
content = content.replace(
    'assert "vnodes" in data',
    'assert "vnodes" in data["plan"]'
)

# 5. Замена assert "offers" in data на assert "offers" in data["plan"]
content = content.replace(
    'assert "offers" in data',
    'assert "offers" in data["plan"]'
)

# 6. Удаление всех add_node_proto_ids/remove_node_proto_ids из json запросов
# Но сохранение структуры, просто убрать эти строки
lines = content.split('\n')
filtered_lines = []
skip_next_comma = False

for i, line in enumerate(lines):
    if '"add_node_proto_ids"' in line or '"remove_node_proto_ids"' in line:
        # Пропускаем эту строку
        # Если следующая строка - просто закрывающая скобка, не добавляем лишнюю запятую
        continue
    else:
        filtered_lines.append(line)

content = '\n'.join(filtered_lines)

# 7. Очистка лишних пустых строк и висячих запятых перед }
content = re.sub(r',\s*\n\s*}', '\n            }', content)
content = re.sub(r',\s*\n\s*\]', '\n            ]', content)

file_path.write_text(content, encoding='utf-8')
print('Fixed test_sub_plans.py')
