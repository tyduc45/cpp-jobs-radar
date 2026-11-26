"""Rank by explicit role level or minimum experience. Unknown roles stay neutral."""
import re
import unicodedata

YEARS = re.compile(
    r"(\d{1,2})(?:\s*[-至到~–]\s*\d{1,2})?\s*\+?\s*"
    r"(?:年(?:以上|及以上|及其以上)?(?:的)?(?:相关|开发|行业|研发|工作|项目|专业|软件)*经验"
    r"|years?['’]?\s+(?:of\s+)?(?:relevant\s+|professional\s+|work\s+|software\s+|development\s+)*experience)", re.I)
DIGITS = str.maketrans("零一二三四五六七八九两", "01234567892")


def rank_role(title, description="", contract=""):
    title = unicodedata.normalize("NFKC", title)
    text = unicodedata.normalize("NFKC", title + ". " + description)
    text = re.sub(r"([一二三四五六七八九]?)十([一二三四五六七八九]?)",
                  lambda m: str(10 * int(m[1].translate(DIGITS) or 1) + int(m[2].translate(DIGITS) or 0)), text).translate(DIGITS)
    years = max((int(m[1]) for m in YEARS.finditer(text)), default=None)
    if re.search(r"资深|高级|专家|架构师|负责人|总监|首席|\b(senior|sr\.?|staff|principal|lead|director|manager)\b", title, re.I) or (years or 0) >= 5:
        return "P4", "高级 / 资深"
    if re.search(r"中级|\bmid[- ]level\b|\bengineer II\b", title, re.I) or (years or 0) >= 3:
        return "P3", "有经验"
    if contract == "intern" or re.search(r"实习|应届|校招|校园招聘|毕业生|管培生|\b(intern(ship)?|new grad(uate)?|graduate|co-op)\b", title, re.I):
        return "P0", "校招 / 实习"
    if re.search(r"初级|助理|\b(junior|entry[- ]level|early career)\b", title, re.I) or re.search(r"经验不限|不限经验|无需工作经验|欢迎应届", text) or years is not None:
        return "P1", "入门 / 低年限"
    return "P2", "资历未注明"
