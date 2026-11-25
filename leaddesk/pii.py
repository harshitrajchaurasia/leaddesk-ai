import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 10-11 digit phone numbers with optional +1, spaces, dots, dashes, parens
PHONE = re.compile(r"(?<![\w-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)")


def mask(text: str) -> str:
    return PHONE.sub("[phone]", EMAIL.sub("[email]", text))
