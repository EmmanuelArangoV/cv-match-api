import re

with open('src/infrastructure/db/models.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('notes: Mapped[str | None] = mapped_column(Text, nullable=True)', 'notes: Mapped[str | None] = mapped_column(String, nullable=True)')

with open('src/infrastructure/db/models.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Fixed models.py Text -> String")
