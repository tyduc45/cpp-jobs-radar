"""Conservative country / work arrangement / contract classification.

Only location fields are geocoded. Ambiguous/unmapped locations stay unknown.
No guesses from company headquarters or timezone/region labels.
"""
import re

# ISO country code, bilingual display name, explicit country names and unambiguous cities.
COUNTRIES = {
    "AU": ("澳大利亚 · Australia", "australia|sydney|melbourne|brisbane|adelaide|canberra|perth|澳大利亚|悉尼|墨尔本"),
    "NZ": ("新西兰 · New Zealand", "new zealand|auckland|wellington|christchurch|新西兰"),
    "US": ("美国 · United States", "united states|usa|u\\.s\\.a\\.?|san francisco|san jose|santa clara|sunnyvale|mountain view|palo alto|menlo park|redwood city|foster city|san mateo|san carlos|cupertino|milpitas|los angeles|san diego|new york|nyc|seattle|bellevue|redmond|boston|cambridge,? ma|chicago|austin|houston|dallas|denver|boulder|pittsburgh|atlanta|washington,? dc|irvine|costa mesa|hawthorne|el segundo|reston|arlington,? va|raleigh|durham,? nc|san antonio|sacramento|oakland|pleasanton|burlingame|palm bay|huntsville|california|texas|virginia|massachusetts|north carolina|colorado|美国"),
    "CA": ("加拿大 · Canada", "canada|toronto|vancouver|montreal|montréal|ottawa|waterloo|quebec|québec|calgary|edmonton|加拿大"),
    "GB": ("英国 · United Kingdom", "united kingdom|uk|u\\.k\\.?|england|scotland|london|manchester|edinburgh|bristol|cambridge,? (?:uk|united kingdom)|英国"),
    "DE": ("德国 · Germany", "germany|deutschland|berlin|munich|münchen|hamburg|frankfurt|stuttgart|düsseldorf|dusseldorf|德国"),
    "FR": ("法国 · France", "france|paris|lyon|toulouse|bordeaux|法国"),
    "NL": ("荷兰 · Netherlands", "netherlands|amsterdam|rotterdam|eindhoven|delft|荷兰"),
    "IE": ("爱尔兰 · Ireland", "ireland|dublin|cork|爱尔兰"),
    "CH": ("瑞士 · Switzerland", "switzerland|zurich|zürich|geneva|lausanne|瑞士"),
    "SE": ("瑞典 · Sweden", "sweden|stockholm|gothenburg|göteborg|瑞典"),
    "FI": ("芬兰 · Finland", "finland|helsinki|espoo|tampere|芬兰"),
    "DK": ("丹麦 · Denmark", "denmark|copenhagen|丹麦"),
    "NO": ("挪威 · Norway", "norway|oslo|挪威"),
    "PL": ("波兰 · Poland", "poland|warsaw|warszawa|krakow|kraków|wroclaw|wrocław|gdansk|gdańsk|波兰"),
    "CZ": ("捷克 · Czechia", "czechia|czech republic|prague|brno|捷克"),
    "ES": ("西班牙 · Spain", "spain|madrid|barcelona|西班牙"),
    "PT": ("葡萄牙 · Portugal", "portugal|lisbon|porto|葡萄牙"),
    "IT": ("意大利 · Italy", "italy|milan|rome|turin|意大利"),
    "AT": ("奥地利 · Austria", "austria|vienna|奥地利"),
    "BE": ("比利时 · Belgium", "belgium|brussels|leuven|比利时"),
    "RO": ("罗马尼亚 · Romania", "romania|bucharest|cluj|罗马尼亚"),
    "HU": ("匈牙利 · Hungary", "hungary|budapest|匈牙利"),
    "EE": ("爱沙尼亚 · Estonia", "estonia|tallinn|爱沙尼亚"),
    "RS": ("塞尔维亚 · Serbia", "serbia|belgrade|塞尔维亚"),
    "UA": ("乌克兰 · Ukraine", "ukraine|kyiv|kiev|lviv|乌克兰"),
    "CN": ("中国大陆 · China", "china|beijing|shanghai|shenzhen|hangzhou|guangzhou|chengdu|中国|北京|上海|深圳|杭州"),
    "HK": ("中国香港 · Hong Kong", "hong kong|hongkong|香港"),
    "TW": ("中国台湾 · Taiwan", "taiwan|taipei|hsinchu|台湾|台北|新竹"),
    "SG": ("新加坡 · Singapore", "singapore|新加坡"),
    "JP": ("日本 · Japan", "japan|tokyo|osaka|yokohama|日本|东京"),
    "KR": ("韩国 · South Korea", "south korea|republic of korea|seoul|韩国|首尔"),
    "IN": ("印度 · India", "india|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|gurgaon|gurugram|chennai|noida|印度"),
    "IL": ("以色列 · Israel", "israel|tel aviv|haifa|herzliya|以色列"),
    "AE": ("阿联酋 · United Arab Emirates", "united arab emirates|uae|dubai|abu dhabi|阿联酋"),
    "TR": ("土耳其 · Türkiye", "turkey|türkiye|istanbul|ankara|土耳其"),
    "BR": ("巴西 · Brazil", "brazil|brasil|sao paulo|são paulo|巴西"),
    "MX": ("墨西哥 · Mexico", "mexico|méxico|guadalajara|monterrey|墨西哥"),
    "AR": ("阿根廷 · Argentina", "argentina|buenos aires|阿根廷"),
    "ZA": ("南非 · South Africa", "south africa|cape town|johannesburg|南非"),
    "KE": ("肯尼亚 · Kenya", "kenya|nairobi|肯尼亚"),
    "NG": ("尼日利亚 · Nigeria", "nigeria|lagos|尼日利亚"),
    "EG": ("埃及 · Egypt", "egypt|cairo|埃及"),
    "MY": ("马来西亚 · Malaysia", "malaysia|kuala lumpur|penang|马来西亚"),
    "VN": ("越南 · Vietnam", "vietnam|viet nam|ho chi minh|hanoi|越南"),
    "TH": ("泰国 · Thailand", "thailand|bangkok|泰国"),
    "PH": ("菲律宾 · Philippines", "philippines|manila|菲律宾"),
    "ID": ("印度尼西亚 · Indonesia", "indonesia|jakarta|印度尼西亚"),
}


def countries_for(location, explicit=None):
    codes = set()
    for value in explicit or []:
        if value in COUNTRIES:
            codes.add(value)
        elif value == "USA":
            codes.add("US")
        elif value == "GBR":
            codes.add("GB")
        else:
            location += "; " + str(value)
    for code, (_, pattern) in COUNTRIES.items():
        if re.search(r"(?<![a-z])(?:" + pattern + r")(?![a-z])", location, re.I):
            codes.add(code)
    if re.search(r"(?:^|[,; /-])US(?:$|[,; /-])", location):
        codes.add("US")
    return sorted(codes)


def classify(title, location, description, employment="", workplace="", explicit_countries=None):
    hint = f"{title} {location} {workplace}"
    mode = "unknown"
    if re.search(r"\bhybrid\b|混合办公", hint, re.I):
        mode = "hybrid"
    elif re.search(r"\b(?:on[ -]?site|in[ -]office)\b|现场办公", hint, re.I):
        mode = "onsite"
    elif re.search(r"\bremote\b|远程", hint, re.I):
        mode = "remote"
    # Only explicit role-level language, not mentions of remote systems or teams.
    elif re.search(r"(?:this (?:role|position) is|work (?:arrangement|model|type)\s*:)\s+(?:a\s+)?hybrid", description, re.I):
        mode = "hybrid"
    elif re.search(r"(?:this (?:role|position) is|work (?:arrangement|model|type)\s*:)\s+(?:fully\s+|100%\s+)?remote", description, re.I):
        mode = "remote"
    elif re.search(r"(?:this (?:role|position) (?:is|requires)|work (?:arrangement|model|type)\s*:)\s+(?:fully\s+)?(?:on[ -]?site|in[ -]office)", description, re.I):
        mode = "onsite"
    contract_hint = f"{title} {employment}"
    if re.search(r"\bintern(?:ship)?\b|\bco[ -]?op\b|\bworking student\b|实习|werkstudent", contract_hint, re.I):
        contract = "intern"
    elif re.search(r"\bfull[ -]?time\b|全职", employment, re.I):
        contract = "fulltime"
    elif re.search(r"\bpart[ -]?time\b|兼职", employment, re.I):
        contract = "parttime"
    elif re.search(r"\bcontract(?:or)?\b|\btemporary\b", employment, re.I):
        contract = "contract"
    elif re.search(r"(?:this (?:role|position) is|employment (?:type|status)\s*:)\s+(?:a\s+)?full[ -]?time", description, re.I):
        contract = "fulltime"
    else:
        contract = "unknown"
    return {"countries": countries_for(location, explicit_countries), "workplace": mode, "contract": contract}
