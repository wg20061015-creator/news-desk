#!/usr/bin/env python3
"""每天抓取 RSS -> 免费翻译(中/韩) -> 生成 docs/index.html。只用标准库,无需任何付费服务。"""
import json, re, time, html, hashlib, os, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (compatible; news-desk-bot)"}
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, "cache.json")

def gn(q, hl="en-US", gl="US", ceid="US:en", when="1d"):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q + " when:" + when, "hl": hl, "gl": gl, "ceid": ceid})

def G(col, tag, q, cap=6, hours=40, lang="en"):
    when = "1d" if hours <= 48 else "%dd" % ((hours + 23) // 24)   # 大佬观点等慢新闻需要更长的检索窗口
    if lang == "ko":
        return (col, tag, gn(q, "ko", "KR", "KR:ko", when), None, hours, cap)
    if lang == "zh":
        return (col, tag, gn(q, "zh-CN", "CN", "CN:zh-Hans", when), None, hours, cap)
    return (col, tag, gn(q, when=when), None, hours, cap)

# (栏目 us美国市场/g全球宏观/geo地缘/v大佬观点/k韩国/c加密, 标签, 网址, 固定来源名, 时间窗口小时, 最多条数)
CNBC_RSS = "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id="
FEEDS = [
 # ---------- 美国市场(对韩股影响最大,放最前) ----------
 ("us", "Fed", "https://www.federalreserve.gov/feeds/press_all.xml", "Federal Reserve", 96, 5),
 ("us", "Fed", "https://www.federalreserve.gov/feeds/speeches.xml", "Federal Reserve", 168, 5),
 # ---------- 官方一手来源(优先级最高)----------
 # 美联储:官员讲话与国会证词(已核实的官方 RSS)、货币政策新闻稿
 ("us", "Fed", "https://www.federalreserve.gov/feeds/speeches_and_testimony.xml", "Federal Reserve", 168, 8),
 ("us", "Fed", "https://www.federalreserve.gov/feeds/testimony.xml", "Federal Reserve", 240, 3),
 ("us", "Fed", "https://www.federalreserve.gov/feeds/press_monetary.xml", "Federal Reserve", 240, 4),
 ("us", "SEC", "https://www.sec.gov/news/pressreleases.rss", "U.S. SEC", 96, 4),
 ("g", "ECB", "https://www.ecb.europa.eu/rss/press.xml", "ECB", 96, 4),
 ("g", "EIA", "https://www.eia.gov/rss/todayinenergy.xml", "U.S. EIA", 96, 3),
 ("g", "Nikkei Asia", "https://asia.nikkei.com/rss/feed/nar", "Nikkei Asia", 40, 6),
 # 韩国央行(BOK)官方 RSS:地址取自 BOK 官网「RSS 서비스」页面
 ("k", "韩央行·决议", "https://www.bok.or.kr/portal/bbs/P0000093/news.rss?menuNo=200789", "한국은행", 240, 3),
 ("k", "韩央行·市场动向", "https://www.bok.or.kr/portal/bbs/P0002017/news.rss?menuNo=200365", "한국은행", 240, 3),
 ("k", "韩央行·指标", "https://www.bok.or.kr/portal/bbs/P0002018/news.rss?menuNo=200366", "한국은행", 48, 2),
 ("k", "韩央行·经济日志", "https://www.bok.or.kr/portal/bbs/P0002329/news.rss?menuNo=200696", "한국은행", 240, 2),
 ("k", "韩央行·国际收支", "https://www.bok.or.kr/portal/bbs/P0002244/news.rss?menuNo=200473", "한국은행", 240, 2),
 ("k", "韩央行·议事录", "https://www.bok.or.kr/portal/bbs/B0000245/news.rss?menuNo=200761", "한국은행", 336, 2),
 ("k", "韩央行·新闻稿", "https://www.bok.or.kr/portal/bbs/P0000559/news.rss?menuNo=200690", "한국은행", 96, 6),
 ("k", "이데일리RSS", "http://rss.edaily.co.kr/edaily_news.xml", "이데일리", 30, 8),
 ("us", "白宫", "https://www.whitehouse.gov/news/feed/", "White House", 72, 4),
 ("us", "BLS", "https://www.bls.gov/feed/bls_latest.rss", "BLS", 96, 4),
 ("us", "MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "MarketWatch", 30, 8),
 ("us", "MW速递", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse", "MarketWatch", 30, 8),
 ("us", "WSJ市场", "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", "WSJ", 30, 8),
 ("us", "CNBC", CNBC_RSS + "10000664", "CNBC", 30, 8),
 ("us", "CNBC头条", CNBC_RSS + "100003114", "CNBC", 30, 6),
 ("us", "Yahoo财经", "https://finance.yahoo.com/news/rssindex", "Yahoo Finance", 30, 6),
 G("us", "美股", "Wall Street stocks S&P 500 Nasdaq Dow close", 8),
 G("us", "美股期货", "stock futures premarket Nasdaq S&P 500 futures", 5),
 G("us", "美国数据", "CPI OR PCE OR \"jobs report\" OR payrolls OR GDP OR \"retail sales\" OR ISM OR \"jobless claims\"", 6),
 G("us", "Fed官员", "Powell OR Warsh OR \"Fed governor\" OR \"Fed official\" interest rates inflation", 6),
 G("us", "特朗普", "Trump (Fed OR tariffs OR economy OR dollar OR \"interest rates\" OR trade OR sanctions)", 6),
 G("us", "美债美元", "Treasury yields OR \"dollar index\" OR \"10-year yield\"", 5),
 G("us", "芯片/AI", "Nvidia OR TSMC OR Micron OR \"SK hynix\" OR HBM OR AI chip demand", 6),
 G("us", "美股财报", "earnings guidance Nvidia OR Micron OR Broadcom OR AMD OR Intel OR Tesla OR Apple", 6),
 G("us", "科技巨头", "Apple OR Microsoft OR Alphabet OR Amazon OR Meta stock AI spending", 5),
 G("us", "美韩关联", "\"South Korea\" OR Korean Samsung OR Hyundai OR \"SK hynix\" tariffs OR investment OR chips", 6),
 G("us", "뉴욕증시", "뉴욕증시 마감 OR 나스닥 OR S&P500 OR 다우", 6, 40, "ko"),
 G("us", "미국반도체", "엔비디아 OR 마이크론 OR 필라델피아반도체 OR 미국 선물", 6, 40, "ko"),
 G("us", "연준", "연준 OR FOMC OR 파월 OR 美 CPI OR 美 고용", 6, 48, "ko"),
 # ---------- 全球宏观与市场 ----------
 G("g", "Reuters", "site:reuters.com (economy OR markets OR Fed OR inflation OR tariffs OR oil OR bonds)", 8),
 G("g", "Bloomberg", "site:bloomberg.com (economy OR markets OR Fed OR inflation OR tariffs OR oil OR bonds)", 8),
 G("g", "WSJ/FT", "(site:wsj.com OR site:ft.com) (markets OR Fed OR economy)", 5),
 G("g", "央行", "ECB OR BOJ OR \"Bank of Japan\" OR PBOC rate decision", 4),
 G("g", "大宗", "oil prices OR gold prices OR copper OR OPEC", 4),
 G("g", "中国", "China economy yuan stimulus property exports", 4),
 G("g", "日本", "yen dollar Japan intervention OR Nikkei", 3),
 # ---------- 地缘政治 ----------
 G("geo", "美中", "US China trade tariffs export controls chips", 6),
 G("geo", "台海", "Taiwan Strait OR South China Sea military tensions", 4),
 G("geo", "中东", "Iran OR Israel OR \"Strait of Hormuz\" OR Gaza oil", 5),
 G("geo", "俄乌", "Russia Ukraine sanctions ceasefire", 4),
 G("geo", "朝鲜", "North Korea missile OR nuclear OR Kim Jong Un", 4),
 G("geo", "북한", "북한 미사일 OR 도발 OR 핵 OR 한미 관세", 4, 40, "ko"),
 G("geo", "制裁", "sanctions OR embargo OR export ban markets", 4),
 # ---------- 大佬/经济学家/策略师观点 ----------
 # 顶级策略师 / 经济学家 / 投资大佬:按人名精准检索,标题或摘要必须出现其姓名才收录
 G("v", "Tom Lee", "\"Tom Lee\" Fundstrat", 3, 120),
 G("v", "Michael Wilson", "\"Michael Wilson\" \"Morgan Stanley\" (stocks OR S&P OR strategist OR equities)", 3, 120),
 G("v", "Kolanovic", "Kolanovic", 3, 240),
 G("v", "Yardeni", "Yardeni", 3, 120),
 G("v", "Jeremy Siegel", "\"Jeremy Siegel\" Wharton", 3, 120),
 G("v", "Ray Dalio", "\"Ray Dalio\" Bridgewater", 3, 120),
 G("v", "Druckenmiller", "Druckenmiller", 3, 168),
 G("v", "Howard Marks", "\"Howard Marks\" Oaktree", 3, 120),
 G("v", "Buffett", "Buffett Berkshire Hathaway", 2, 96),
 G("v", "策略师(韩文)", "톰 리 OR 레이 달리오 OR 하워드 막스 OR 드러켄밀러 OR 제러미 시겔 OR 마이클 윌슨 OR 워런 버핏 OR 데이비드 코스틴 OR 댄 아이브스 OR 에드 야데니 OR 티모시 모 OR 조너선 가너 OR 사비타 서브라마니안", 6, 120, "ko"),
 G("v", "华尔街策略", "(Goldman Sachs OR \"Morgan Stanley\" OR JPMorgan OR \"Bank of America\") strategist S&P 500 target OR outlook", 4, 72),
 G("v", "看韩国", "Goldman OR \"Morgan Stanley\" OR JPMorgan OR Nomura OR UBS KOSPI OR Korea outlook OR \"Korean stocks\"", 4, 96),
 # ---- 顶级策略师(与 Kostin / Wilson / Subramanian 等同级),按姓名精准检索 ----
 G("v", "David Kostin", "\"David Kostin\" Goldman Sachs", 3, 168),
 G("v", "Savita Subramanian", "\"Savita Subramanian\" \"Bank of America\"", 3, 168),
 G("v", "Lakos-Bujas", "\"Lakos-Bujas\" JPMorgan", 3, 168),
 G("v", "Binky Chadha", "\"Binky Chadha\" Deutsche Bank", 3, 168),
 G("v", "Lori Calvasina", "\"Lori Calvasina\" RBC", 3, 168),
 G("v", "Scott Chronert", "\"Scott Chronert\" Citi", 3, 168),
 G("v", "Chris Verrone", "\"Chris Verrone\" Strategas", 3, 168),
 G("v", "Mark Newton", "\"Mark Newton\" Fundstrat", 3, 168),
 G("v", "Dan Ives", "\"Dan Ives\" Wedbush", 4, 96),
 G("v", "Timothy Moe", "\"Timothy Moe\" Goldman Sachs Asia", 3, 240),
 G("v", "Jonathan Garner", "\"Jonathan Garner\" \"Morgan Stanley\"", 3, 240),
 G("v", "洪灏", "洪灏 策略 OR 美股 OR A股 OR 港股", 3, 168, "zh"),
 G("v", "亚洲策略(含韩国)", "(\"Timothy Moe\" OR \"Jonathan Garner\" OR Goldman OR \"Morgan Stanley\") (Korea OR KOSPI OR \"Asia ex-Japan\") strategist", 4, 120),
 G("v", "KOSPI目标价", "KOSPI (target OR forecast OR \"year-end\" OR upgrade) (Goldman OR JPMorgan OR Nomura OR Citi OR UBS OR Macquarie OR \"Morgan Stanley\")", 4, 120),
 G("v", "韩国券商展望", "리서치센터장 코스피 전망 OR 투자전략 OR 증시 전망", 5, 72, "ko"),
 # ---------- 加密货币 ----------
 ("c", "CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk", 40, 6),
 ("c", "Cointelegraph", "https://cointelegraph.com/rss", "Cointelegraph", 40, 6),
 G("c", "比特币", "Bitcoin OR BTC price ETF flows", 6),
 G("c", "以太坊", "Ethereum OR Solana OR XRP price OR upgrade", 4),
 G("c", "监管", "crypto regulation SEC OR CFTC OR stablecoin OR GENIUS Act", 5),
 G("c", "机构", "Strategy OR MicroStrategy OR BlackRock OR Coinbase bitcoin treasury", 4),
 G("c", "비트코인", "비트코인 OR 이더리움 OR 업비트 OR 빗썸 시세", 6, 40, "ko"),
 G("c", "가상자산", "가상자산 규제 OR 스테이블코인 OR 원화 스테이블코인 OR 금융위 가상자산", 5, 48, "ko"),
 # ---------- 韩国 ----------
 ("k", "연합뉴스", "https://en.yna.co.kr/RSS/economy.xml", "Yonhap", 48, 8),
 ("k", "연합뉴스KR", "https://www.yna.co.kr/rss/economy.xml", "연합뉴스", 30, 8),
 ("k", "한국경제", "https://www.hankyung.com/feed/economy", "한국경제", 30, 8),
 ("k", "매일경제", "https://www.mk.co.kr/rss/30100041/", "매일경제", 30, 8),
 ("k", "Korea Times", "https://www.koreatimes.co.kr/www/rss/economy.xml", "Korea Times", 48, 6),
 ("k", "Korea Herald", "https://www.koreaherald.com/common/rss_xml.php?ct=102", "Korea Herald", 48, 6),
 G("k", "KOSPI", "KOSPI OR KOSDAQ OR \"Seoul shares\" OR \"Korean stocks\"", 6),
 G("k", "코스피", "코스피 OR 코스닥 OR 증시 마감", 6, 40, "ko"),
 G("k", "환율", "원달러 환율 OR 원화 OR 외환시장", 5, 40, "ko"),
 G("k", "외국인", "외국인 순매도 OR 순매수 OR 수급 코스피", 5, 40, "ko"),
 G("k", "반도체", "삼성전자 OR SK하이닉스 OR 반도체 수출 OR HBM", 6, 40, "ko"),
 G("k", "실적", "삼성전자 OR SK하이닉스 OR 현대차 실적 OR 컨센서스 OR 목표주가", 5, 40, "ko"),
 G("k", "선물옵션", "코스피200 선물 OR 옵션 만기 OR 프로그램 매매 OR 사이드카 OR 서킷브레이커", 5, 40, "ko"),
 G("k", "MSCI", "MSCI 한국 OR 선진국 지수 편입 OR 밸류업 지수 OR 외국인 투자", 4, 72, "ko"),
 G("k", "정책", "금융위원회 OR 금융감독원 OR 공매도 OR 밸류업 OR 증시 부양 OR 상법 개정", 6, 48, "ko"),
 G("k", "정부", "기획재정부 OR 대통령실 OR 국회 경제 정책 OR 추경 OR 세제", 5, 48, "ko"),
 G("k", "한은", "한국은행 기준금리 OR 금통위 OR 물가 OR 가계부채", 5, 48, "ko"),
 G("k", "산업", "2차전지 OR 조선 OR 방산 OR 자동차 OR 바이오 주가", 5, 40, "ko"),
 G("k", "한미무역", "한미 관세 OR 한국 수출 OR 무역수지 OR 대미 투자", 5, 48, "ko"),
 # ---- 韩国市场专项:熔断/指数事件/税制/公示财报/资金与程序化/专业财经媒体 ----
 G("k", "熔断·暂停交易", "사이드카 OR 서킷브레이커 OR 매매거래정지 OR 거래 정지 코스피 OR 코스닥", 4, 48, "ko"),
 G("k", "指数事件", "MSCI 편입 OR 코스피200 정기변경 OR 선물옵션 만기 OR 외국인 한도 OR 지수 리밸런싱", 4, 72, "ko"),
 G("k", "税制·股东", "금투세 OR 배당소득 분리과세 OR 대주주 양도세 OR 증권거래세 OR 상법 개정", 4, 72, "ko"),
 G("k", "公示·财报", "삼성전자 OR SK하이닉스 OR 현대차 실적 OR 공시 OR 자사주 OR 영업이익 잠정", 5, 40, "ko"),
 G("k", "资金·程序化", "기관 순매수 OR 프로그램 매매 OR 연기금 OR 개인 순매수 OR 신용융자 코스피", 4, 40, "ko"),
 G("k", "이데일리", "site:edaily.co.kr (증시 OR 코스피 OR 환율 OR 금리)", 5, 40, "ko"),
 G("k", "서울경제", "site:sedaily.com (증시 OR 코스피 OR 반도체 OR 환율)", 5, 40, "ko"),
 G("k", "머니투데이", "site:mt.co.kr (증시 OR 코스피 OR 환율 OR 반도체)", 5, 40, "ko"),
 G("k", "연합인포맥스", "연합인포맥스 (코스피 OR 환율 OR 채권 OR 증시)", 5, 40, "ko"),
 G("k", "外资看韩国", "Korea stocks foreign investors OR \"Korea discount\" OR chaebol reform OR \"MSCI Korea\"", 4, 48),
 G("k", "BOK", "\"Bank of Korea\" OR Korean won OR Korea exports OR Korea inflation", 5),
 # ---------- 官方域名限定检索(Google News 的 site: 过滤)----------
 G("k", "金融委·金监院", "site:fsc.go.kr OR site:fss.or.kr", 6, 72, "ko"),
 G("k", "财经部·产业部", "site:mofe.go.kr OR site:motir.go.kr OR site:mpb.go.kr", 5, 72, "ko"),
 G("k", "关税厅·统计·交易所", "site:customs.go.kr OR site:mods.go.kr OR site:krx.co.kr", 5, 72, "ko"),
 G("k", "政策简报(官方)", "site:korea.kr (금융위원회 OR 재정경제부 OR 산업통상부 OR 관세청 OR 한국은행 OR 수출 OR 증시 OR 금리)", 6, 72, "ko"),
 G("us", "美财政部/OFAC", "site:treasury.gov (sanctions OR tariffs OR Treasury OR bonds OR OFAC)", 4, 72),
 G("us", "美商务部/BEA", "(site:bea.gov OR site:commerce.gov OR site:census.gov) (GDP OR PCE OR trade OR retail)", 3, 96),
 G("g", "IMF/BIS/OECD", "(site:imf.org OR site:bis.org OR site:oecd.org OR site:worldbank.org) (outlook OR forecast OR report OR warns)", 4, 120),
 G("g", "日本央行/财务省", "site:boj.or.jp OR site:mof.go.jp", 3, 96),
]
MAX = {"us": 60, "g": 30, "geo": 20, "v": 45, "k": 85, "c": 28}

# ---------- 质量过滤:剔除娱乐/体育/股价页垃圾/新闻稿网站 ----------
BLOCK_SRC = re.compile(r"ad-hoc-news|8days|prnewswire|pr newswire|globenewswire|business wire|accesswire|einpresswire|openpr|marketbeat|simply wall st|insider monkey|motley fool|zacks|litefinance|traders union|cryptorank|crypto rank|business news this week|shattered\\.io|dainik|gujarat samachar|mathrubhumi|vietnam\\.vn|nacionale|inc\\.com|times of oman", re.I)
BLOCK_TITLE = re.compile(r"forecast (and|&) predictions?|price predictions?|부고|부음|별세|\bobituary\b|\bdies at\b|\bpasses away\b|반려|펫보험|자동차보험|보험료 할인|육아|맛집|여행지|레시피|다이어트|결혼|연애|뷰티|웹툰|드라마|아이돌|\bpet insurance\b|\bdating\b|\bwedding\b|\btravel tips\b|stock price (&|and) latest news|stock quote|horoscope|celebrity|kardashian|taylor swift|\bfashion\b|\boutfit\b|lifestyle|\brecipes?\b|lottery|box office|royal family|\b(nfl|nba|mlb|nhl)\b|premier league|world cup|olympic|연예|운세|로또|예능|야구|축구|농구|배구", re.I)
# 来源权威度加分(越权威越靠前)
SRC_W = [("federal reserve", 4), ("bank of korea", 4), ("한국은행", 4), ("금융위원회", 3), ("금융감독원", 3), ("재정경제부", 3), ("기획재정부", 3),
         ("한국거래소", 3), ("관세청", 3), ("u.s. sec", 3), ("ecb", 3), ("treasury", 3), ("정책브리핑", 2), ("imf", 2), ("u.s. eia", 2),
         ("white house", 2), ("bls", 3), ("reuters", 2), ("bloomberg", 2), ("wsj", 2),
         ("wall street journal", 2), ("financial times", 2), ("cnbc", 2), ("yonhap", 2), ("연합뉴스", 2),
         ("한국경제", 2), ("매일경제", 2), ("marketwatch", 1), ("yahoo", 1), ("korea herald", 1),
         ("korea times", 1), ("nikkei", 1), ("barron", 1), ("investing.com", 1), ("coindesk", 1), ("cointelegraph", 1)]

# ---------- 精准过滤:所有来源都要和金融/市场/宏观/地缘直接相关 ----------
STRONG = re.compile(
    r"\bstocks?\b|equit|\bshares\b|\bmarkets?\b|\bindex\b|indices|kospi|kosdaq|nasdaq|\bdow\b|s&p|nikkei|\bfed\b|fomc|powell|warsh|"
    r"treasur|\byields?\b|\bbonds?\b|inflation|\bcpi\b|\bpce\b|\bgdp\b|payroll|jobs report|unemployment|tariff|sanction|export control|"
    r"\brates?\b|\bwon\b|dollar|\byen\b|yuan|\beuro\b|currenc|forex|\boil\b|crude|opec|\bgold\b|copper|bitcoin|\bbtc\b|\bether(eum)?\b|crypto|"
    r"stablecoin|\betfs?\b|earnings|profit|revenue|guidance|\bipo\b|merger|acquisition|buyout|private credit|\bloans?\b|\bdebt\b|deficit|"
    r"recession|stimulus|nvidia|tsmc|micron|broadcom|\bamd\b|\bintel\b|samsung|hynix|\bhbm\b|semiconductor|\bchips?\b|hyundai|"
    r"central bank|\becb\b|\bbo[jk]\b|pboc|trade (war|deal|talks|surplus|deficit)|supply chain|buffett|berkshire|dalio|druckenmiller|yardeni|"
    r"주가|증시|코스피|코스닥|환율|금리|수출|수입|무역|관세|반도체|삼성|하이닉스|현대차|기아|물가|성장률|외국인|채권|국채|한국은행|금통위|증권|펀드|"
    r"배당|실적|영업이익|상장|유가|원화|달러|대출|가계부채|추경|금감원|공매도|밸류업|조원|엔비디아|비트코인|가상자산|스테이블|나스닥|뉴욕증시|"
    r"선물|옵션|연준|파월|워시|기준금리|목표주가", re.I)
WEAK = re.compile(r"economy|economic|invest|\bfunds?\b|\bbank|billion|trillion|\bprices?\b|\bgrowth\b|\btax|budget|경제|투자|은행|금융|억 달러|재정|예산|세금|가격", re.I)
GEO = re.compile(r"\bwar\b|missile|taiwan|hormuz|ceasefire|iran|israel|russia|ukraine|north korea|south china sea|embargo|전쟁|미사일|북한|대만|중동|휴전|제재", re.I)
VOICE_RE = re.compile(
    r"fundstrat|kolanovic|yardeni|siegel|dalio|druckenmiller|howard marks|buffett|berkshire|hatzius|kostin|subramanian|lakos|binky chadha|"
    r"calvasina|chronert|verrone|dan ives|wedbush|timothy moe|jonathan garner|洪灏|hong hao|"
    r"마이클 윌슨|콜라노비치|예다니|야데니|시겔|달리오|드러켄밀러|하워드 막스|버핏|버크셔|코스틴|서브라마니안|라코스|칼바시나|크로너트|베로니|"
    r"댄 아이브스|웨드부시|티모시 모|조너선 가너|톰 리", re.I)
# 容易重名的人名:必须同时出现金融语境才收录
AMBIG = [(re.compile(r"wilson", re.I), re.compile(r"morgan stanley|strategist|s&p|equit|stocks|\bcio\b|모건스탠리", re.I)),
         (re.compile(r"tom lee", re.I), re.compile(r"fundstrat|bitcoin|ether|s&p|stocks|equit|bitmine|strategist|펀드스트랫", re.I)),
         (re.compile(r"mark newton", re.I), re.compile(r"fundstrat|technical|chart|s&p|stocks", re.I))]

def voice_ok(text):
    if VOICE_RE.search(text):
        return True
    return any(n.search(text) and c.search(text) for n, c in AMBIG)

# 与韩股有直接/间接联动的新闻(非韩国栏目也会被标记「韩股关联」并加分)
KR_LINK = re.compile(
    r"korea|\bkospi\b|kosdaq|korean won|seoul|samsung|hynix|\bhbm\b|\bdram\b|\bnand\b|memory (chip|price)|micron|nvidia|tsmc|semiconductor|"
    r"chip ?(stocks|makers|export|ban|curb)|chaebol|hyundai|\bkia\b|lg energy|posco|shipbuild|msci (em|emerging|asia|korea)|emerging market|"
    r"asia(n)? (stocks|markets|equities)|export control|section 232|(tariff|trade).{0,40}(chip|semiconductor|auto|steel|asia)|dollar index|strong dollar|"
    r"한국|코스피|삼성|하이닉스|반도체|엔비디아|마이크론|환율|원화", re.I)
# 市场警报:熔断、暂停交易、违约、银行挤兑等极端事件
ALERT_RE = re.compile(
    r"사이드카|서킷브레이커|매매거래 ?(정지|중단)|거래 ?정지|반대매매|trading halt|circuit breaker|limit[- ]down|flash crash|"
    r"emergency (rate|meeting)|bank run|bank failure|(sovereign|debt|bond) default|government shutdown|black monday|margin call|forced liquidation", re.I)
# 策略师目标价自动提取(只从标题提取,附原文链接,仅供参考)
TARGET_RE = re.compile(r"(s&p ?500|s&p|nasdaq|dow|kospi|코스피|kosdaq|코스닥|nikkei|msci korea)[^\d]{0,60}?(\d{1,2},\d{3}|\d{3,5})(?!\d)", re.I)
TARGET_CTX = re.compile(r"target|forecast|\bsees?\b|raise|lift|cut|hike|predict|upgrade|downgrade|\bhit\b|reach|could|목표|전망|상향|하향|예상|간다|돌파", re.I)
TARGET_RANGE = {"s&p 500": (4000, 12000), "nasdaq": (12000, 40000), "dow": (30000, 80000), "kospi": (1500, 15000),
                "kosdaq": (400, 2500), "nikkei": (25000, 90000), "msci korea": (300, 2000)}
TARGET_FIRM = re.compile(r"goldman|morgan stanley|jpmorgan|j\.p\. morgan|bank of america|bofa|deutsche|rbc|citi|ubs|nomura|macquarie|barclays|"
                         r"wells fargo|wedbush|strategas|fundstrat|yardeni|evercore|bernstein|hsbc|골드만|모건스탠리|jp모건|씨티|노무라|맥쿼리", re.I)

def norm_idx(x):
    x = x.lower().replace(" ", "")
    if x.startswith("s&p"): return "s&p 500"
    if x in ("코스피", "kospi"): return "kospi"
    if x in ("코스닥", "kosdaq"): return "kosdaq"
    if x.startswith("nasdaq"): return "nasdaq"
    return {"dow": "dow", "nikkei": "nikkei", "mscikorea": "msci korea"}.get(x, x)

def extract_target(title, tag):
    if not TARGET_CTX.search(title):
        return None
    m = TARGET_RE.search(title)
    if not m:
        return None
    idx = norm_idx(m.group(1))
    num = int(m.group(2).replace(",", ""))
    lo, hi = TARGET_RANGE.get(idx, (0, 10**9))
    if not lo <= num <= hi:
        return None
    firm = TARGET_FIRM.search(title)
    generic = {"华尔街策略", "看韩国", "KOSPI目标价", "韩国券商展望", "策略师(韩文)", "亚洲策略(含韩国)"}
    who = (firm.group(0).title() if firm else None) if tag in generic else tag
    if not who:
        return None
    return {"idx": {"s&p 500": "S&P 500", "nasdaq": "Nasdaq", "dow": "Dow", "kospi": "KOSPI", "kosdaq": "KOSDAQ",
                    "nikkei": "Nikkei", "msci korea": "MSCI Korea"}[idx], "num": num, "who": who}

OFFICIAL = {"Fed", "BLS", "SEC", "ECB", "EIA"}
HOUSE_TAGS = {"华尔街策略", "看韩国", "KOSPI目标价", "韩国券商展望", "亚洲策略(含韩国)"}

def passes(col, tag, title, desc):
    """是否保留:官方源直接保留;大佬栏必须出现人名;其余必须标题含金融关键词(或摘要含关键词且有经济语境)。"""
    if tag in OFFICIAL or tag.startswith("韩央行"):
        return True
    desc = desc or ""
    if col == "v":
        if tag in HOUSE_TAGS and STRONG.search(title):   # 机构/券商类检索没有固定人名,只要标题是金融内容即可
            return True
        return voice_ok(title + " " + desc)
    if STRONG.search(title) or (col == "geo" and GEO.search(title)):
        return True
    return bool(STRONG.search(desc)) and bool(WEAK.search(title + " " + desc))

# 官方/一手来源:来源名命中即标记「官方」并加分
OFFICIAL_SRC_RE = re.compile(
    r"federal reserve|\bfomc\b|bureau of labor|\bbls\b|\bbea\b|\btreasury\b|u\.s\. sec\b|securities and exchange|white house|european central bank|\becb\b|"
    r"bank of korea|bank of japan|\bimf\b|\bbis\b|world bank|\boecd\b|u\.s\. eia|energy information|"
    r"한국은행|금융위원회|금융감독원|재정경제부|기획재정부|기획예산처|산업통상|관세청|한국거래소|국가데이터처|통계청|정책브리핑|국세청|공정거래위원회", re.I)

def src_bonus(s):
    s = (s or "").lower()
    for k, v in SRC_W:
        if k in s:
            return v
    return 0

def toks(t):
    t = t.lower()
    w = set(re.findall(r"[a-z0-9$%.]{3,}", t))
    for run in re.findall(r"[가-힣一-鿿]+", t):
        w.update(run[i:i + 2] for i in range(len(run) - 1))
    return w

def cluster(items):
    """把多家媒体报道的同一事件合并为一条:保留最权威来源,并记录有几家在报道(多源=重要性信号)。"""
    order = sorted(items, key=lambda x: (-src_bonus(x["src"]), x["dt"]))
    reps, by_key = [], {}
    for it in order:
        tk = toks(it["title"]); it["_tk"] = tk
        nk = nkey(it["title"])
        hit = by_key.get(nk)
        if hit is None and len(tk) >= 4:
            for r in reps:
                a = r["_tk"]
                if len(a) >= 4 and len(tk & a) / len(tk | a) >= 0.5:
                    hit = r; break
        if hit:
            hit["srcs"].add(it["src"])
        else:
            it["srcs"] = {it["src"]}
            reps.append(it); by_key[nk] = it
    return sorted(reps, key=lambda x: x["dt"], reverse=True)

# 关键词打分:用于"今日要点"排序和"影响"标签(规则判断,非AI分析)
KW = [
 (5, r"fomc|rate hike|rate cut|warsh|powell|기준금리|금통위"),
 (4, r"kospi|코스피|코스닥|원달러|환율|foreign investors|외국인|순매도|순매수"),
 (4, r"tariff|관세|export control|sanction|제재|embargo"),
 (4, r"war|missile|nuclear|taiwan|hormuz|north korea|북한|미사일|전쟁|ceasefire"),
 (3, r"nvidia|tsmc|hbm|samsung|hynix|삼성전자|하이닉스|반도체|semiconductor|chip"),
 (4, r"tom lee|fundstrat|michael wilson|kolanovic|yardeni|jeremy siegel|dalio|druckenmiller|howard marks|buffett|톰 리|달리오|드러켄밀러|하워드 막스|버핏"),
 (3, r"dimon|summers|krugman|el-erian"),
 (3, r"short selling|공매도|밸류업|금융위|금감원|증시 부양|stimulus|추경"),
 (3, r"inflation|cpi|pce|jobs report|payroll|gdp|물가|고용"),
 (3, r"bitcoin|btc|ethereum|crypto|stablecoin|비트코인|가상자산|스테이블코인|etf"),
 (4, r"nasdaq|s&p 500|wall street|dow jones|뉴욕증시|나스닥|필라델피아|futures|선물"),
 (3, r"earnings|guidance|실적|컨센서스|micron|broadcom|amd|마이크론|목표주가"),
 (3, r"sidecar|사이드카|서킷브레이커|circuit breaker|동시만기|msci"),
 (2, r"oil|opec|gold|treasury|yield|dollar|yen|유가|금리"),
 (2, r"plunge|surge|crash|record|slump|soar|급락|급등|폭락|사상 최고"),
]
IMPACT = [
 ("rate", r"fed|fomc|rate hike|rate cut|powell|warsh|금리|기준금리|금통위"),
 ("fx", r"korean won|dollar index|yen|환율|원달러|원화|\bwon\b"),
 ("semi", r"chip|semiconductor|nvidia|tsmc|hbm|samsung|hynix|반도체|삼성전자|하이닉스"),
 ("geo", r"war|missile|taiwan|sanction|iran|israel|russia|north korea|북한|미사일|전쟁|hormuz"),
 ("trade", r"tariff|trade war|export control|관세|수출 규제"),
 ("flow", r"foreign investors|net sell|net buy|outflow|inflow|외국인|순매도|순매수"),
 ("policy", r"short selling|공매도|밸류업|금융위|금감원|stimulus|증시 부양|추경|상법"),
 ("energy", r"\boil\b|opec|crude|유가"),
 ("us", r"nasdaq|s&p 500|wall street|dow jones|뉴욕증시|나스닥|미국 증시|futures"),
 ("earn", r"earnings|guidance|실적|컨센서스|목표주가"),
 ("crypto", r"bitcoin|btc|ethereum|crypto|stablecoin|비트코인|가상자산|스테이블코인|업비트|빗썸"),
]

def score_item(text, col, age_h):
    t = text.lower()
    sc = sum(w for w, p in KW if re.search(p, t))
    sc += 1 if col in ("k", "us") else 0
    sc += 2 if age_h < 3 else (1 if age_h < 8 else 0)
    imp = [k for k, p in IMPACT if re.search(p, t)][:3]
    return sc, imp


from zoneinfo import ZoneInfo
NY = ZoneInfo("America/New_York")

def _us(date, hm, zh, ko, kind, url):
    y, m, d = map(int, date.split("-")); h, mi = map(int, hm.split(":"))
    k = datetime(y, m, d, h, mi, tzinfo=NY).astimezone(KST)
    return {"k": kind, "zh": zh, "ko": ko, "kst": k.strftime("%Y-%m-%dT%H:%M"),
            "t": k.strftime("%m/%d %H:%M KST"), "url": url}

def _kr(date, zh, ko, url="https://www.bok.or.kr/eng/main/contents.do?menuNo=400242", kind="bok"):
    return {"k": kind, "zh": zh, "ko": ko, "kst": date + "T10:00", "t": None, "url": url}

BLS = "https://www.bls.gov/schedule/news_release/"
FED = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
# 日程已对照美联储、BLS、韩国央行官方公布/报道核实(截至 2026-11-21)。到期后请更新此列表。
CAL = [
 _us("2026-11-25", "08:30", "美国10月核心PCE物价", "미국 10월 근원 PCE 물가", "pce", "https://www.bea.gov/news/schedule"),
 _kr("2026-11-26", "韩国央行金融通货委员会(今年最后一次例会)", "한국은행 금융통화위원회 (올해 마지막 정기회의)"),
 _us("2026-12-04", "08:30", "美国11月非农就业报告", "미국 11월 비농업 고용보고서", "nfp", BLS),
 _us("2026-12-09", "14:00", "FOMC利率决议 + 经济预测(SEP)", "FOMC 금리 결정 + 경제전망(SEP)", "fomc", FED),
 _us("2026-12-10", "08:30", "美国11月CPI", "미국 11월 CPI", "cpi", BLS),
 _kr("2027-01-14", "韩国央行基准利率决议", "한국은행 기준금리 결정"),
 _us("2027-01-08", "08:30", "美国12月非农就业报告", "미국 12월 비농업 고용보고서", "nfp", BLS),
 _us("2027-01-13", "08:30", "美国12月CPI", "미국 12월 CPI", "cpi", BLS),
 _us("2027-01-27", "14:00", "FOMC利率决议", "FOMC 금리 결정", "fomc", FED),
 _us("2027-02-05", "08:30", "美国1月非农就业报告", "미국 1월 비농업 고용보고서", "nfp", BLS),
 _us("2027-02-11", "08:30", "美国1月CPI", "미국 1월 CPI", "cpi", BLS),
 _kr("2027-02-25", "韩国央行基准利率决议", "한국은행 기준금리 결정"),
 _us("2027-03-05", "08:30", "美国2月非农就业报告", "미국 2월 비농업 고용보고서", "nfp", BLS),
 _us("2027-03-10", "08:30", "美国2月CPI", "미국 2월 CPI", "cpi", BLS),
 _us("2027-03-17", "14:00", "FOMC利率决议 + 经济预测(SEP)", "FOMC 금리 결정 + 경제전망(SEP)", "fomc", FED),
 _us("2027-04-02", "08:30", "美国3月非农就业报告", "미국 3월 비농업 고용보고서", "nfp", BLS),
 _kr("2027-04-09", "韩国央行基准利率决议", "한국은행 기준금리 결정"),
 _us("2027-04-13", "08:30", "美国3月CPI", "미국 3월 CPI", "cpi", BLS),
 _us("2027-04-28", "14:00", "FOMC利率决议", "FOMC 금리 결정", "fomc", FED),
]
# 休市/到期日按交易所惯例规则推算,请以交易所公告为准
NYSE = "https://www.nyse.com/markets/hours-calendars"
KRX = "https://global.krx.co.kr/"
CAL += [
 _us("2026-11-26", "09:30", "美股感恩节休市(韩股次日无隔夜美盘可参考)", "미국 추수감사절 휴장", "hol", NYSE),
 _us("2026-11-27", "13:00", "美股提前收盘(感恩节次日,成交清淡)", "미국 증시 조기 폐장(추수감사절 다음날)", "hol", NYSE),
 _kr("2026-12-10", "韩国股指期货·期权同时到期日(四巫日,波动加大)", "한국 선물·옵션 동시만기일(변동성 주의)", KRX, "krx"),
 _us("2026-12-18", "16:00", "美股四巫日(期货期权同时到期)", "미국 네 마녀의 날(선물·옵션 동시만기)", "opex", NYSE),
 _us("2026-12-25", "09:30", "美股圣诞节休市", "미국 크리스마스 휴장", "hol", NYSE),
 _kr("2026-12-25", "韩国股市休市(圣诞节)", "한국 증시 휴장(성탄절)", KRX, "krx"),
 _kr("2026-12-31", "韩国股市年末休市", "한국 증시 연말 휴장", KRX, "krx"),
 _kr("2027-03-11", "韩国股指期货·期权同时到期日(四巫日)", "한국 선물·옵션 동시만기일", KRX, "krx"),
]
CAL.sort(key=lambda e: e["kst"])

# (分组, 雅虎代码, 中文, 韩文, 小数位, 类型)  类型 y=收益率(显示bp变化)
MKT = [
 ("kr", "^KS11", "KOSPI", "코스피", 2, ""),
 ("kr", "^KQ11", "KOSDAQ", "코스닥", 2, ""),
 ("kr", "^KS200", "KOSPI 200", "코스피200", 2, ""),
 ("kr", "KRW=X", "美元/韩元", "원/달러", 2, ""),
 ("kr", "005930.KS", "三星电子", "삼성전자", 0, ""),
 ("kr", "000660.KS", "SK海力士", "SK하이닉스", 0, ""),
 ("kr", "EWY", "EWY(美股上市韩国ETF)", "EWY(미국상장 한국 ETF)", 2, ""),
 ("kr2", "005380.KS", "现代汽车", "현대차", 0, ""),
 ("kr2", "000270.KS", "起亚", "기아", 0, ""),
 ("kr2", "373220.KS", "LG新能源", "LG에너지솔루션", 0, ""),
 ("kr2", "006400.KS", "三星SDI", "삼성SDI", 0, ""),
 ("kr2", "207940.KS", "三星生物", "삼성바이오로직스", 0, ""),
 ("kr2", "068270.KS", "赛特瑞恩", "셀트리온", 0, ""),
 ("kr2", "012450.KS", "韩华航空航天", "한화에어로스페이스", 0, ""),
 ("kr2", "035420.KS", "NAVER", "네이버", 0, ""),
 ("kr2", "105560.KS", "KB金融", "KB금융", 0, ""),
 ("kr2", "005490.KS", "POSCO控股", "POSCO홀딩스", 0, ""),
 ("us", "^GSPC", "标普500", "S&P 500", 2, ""),
 ("us", "^IXIC", "纳斯达克", "나스닥", 2, ""),
 ("us", "^DJI", "道琼斯", "다우", 2, ""),
 ("us", "^SOX", "费城半导体", "필라델피아 반도체", 2, ""),
 ("us", "ES=F", "标普500期货", "S&P500 선물", 2, ""),
 ("us", "NQ=F", "纳指100期货", "나스닥100 선물", 2, ""),
 ("us", "^VIX", "VIX恐慌指数", "VIX 변동성", 2, ""),
 ("us2", "NVDA", "英伟达", "엔비디아", 2, ""),
 ("us2", "MU", "美光", "마이크론", 2, ""),
 ("us2", "TSM", "台积电(ADR)", "TSMC(ADR)", 2, ""),
 ("us2", "AMD", "AMD", "AMD", 2, ""),
 ("us2", "TSLA", "特斯拉", "테슬라", 2, ""),
 ("us2", "AAPL", "苹果", "애플", 2, ""),
 ("mac", "^TNX", "美国10年期国债收益率", "미국 10년물 금리", 3, "y"),
 ("mac", "DX-Y.NYB", "美元指数", "달러인덱스", 2, ""),
 ("mac", "JPY=X", "美元/日元", "엔/달러", 3, ""),
 ("mac", "CNY=X", "美元/人民币", "위안/달러", 4, ""),
 ("mac", "CL=F", "WTI原油", "WTI 유가", 2, ""),
 ("mac", "BZ=F", "布伦特原油", "브렌트유", 2, ""),
 ("mac", "HG=F", "铜", "구리", 3, ""),
 ("mac", "GC=F", "黄金", "금", 2, ""),
 ("cr", "BTC-USD", "比特币", "비트코인", 0, ""),
 ("cr", "ETH-USD", "以太坊", "이더리움", 2, ""),
 ("cr", "SOL-USD", "Solana", "솔라나", 2, ""),
 ("cr", "XRP-USD", "XRP", "리플(XRP)", 4, ""),
 ("as", "^N225", "日经225", "닛케이225", 2, ""),
 ("as", "000001.SS", "上证指数", "상하이종합", 2, ""),
 ("as", "^HSI", "恒生指数", "항셍", 2, ""),
]

def _quote(spec):
    grp, sym, zh, ko, dec, typ = spec
    res, err = None, None
    for host in ("query1", "query2"):
        try:
            url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?interval=1d&range=5d" % (host, urllib.parse.quote(sym))
            res = json.loads(get(url, 15).decode("utf-8"))["chart"]["result"][0]
            break
        except Exception as e:
            err = e
    if not res:
        print("quote fail", sym, err)
        return None
    try:
        meta = res["meta"]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        price = meta.get("regularMarketPrice") or closes[-1]
        prev = closes[-2] if len(closes) >= 2 else meta.get("chartPreviousClose")
        chg = price - prev
        t = datetime.fromtimestamp(meta["regularMarketTime"], KST).strftime("%m/%d %H:%M")
        return {"g": grp, "s": sym, "zh": zh, "ko": ko, "d": dec, "y": typ == "y",
                "p": price, "c": chg, "pc": chg / prev * 100 if prev else 0, "t": t}
    except Exception as e:
        print("quote parse fail", sym, e)
        return None

def fetch_market():
    with ThreadPoolExecutor(6) as ex:
        return [r for r in ex.map(_quote, MKT) if r]

def fetch_kimchi(market):
    """泡菜溢价 = 韩国Upbit的BTC韩元价 / (国际BTC美元价 x 美元兑韩元) - 1。公开接口,无需密钥。"""
    try:
        res = json.loads(get("https://api.upbit.com/v1/ticker?markets=KRW-BTC,KRW-ETH,KRW-XRP", 20).decode("utf-8"))
        up = {r["market"]: r for r in res}
        btc = next((r for r in market if r["s"] == "BTC-USD"), None)
        fx = next((r for r in market if r["s"] == "KRW=X"), None)
        out = {"btc_krw": up["KRW-BTC"]["trade_price"], "pc": up["KRW-BTC"]["signed_change_rate"] * 100}
        if btc and fx:
            out["premium"] = (out["btc_krw"] / (btc["p"] * fx["p"]) - 1) * 100
        return out
    except Exception as e:
        print("upbit fail", e)
        return None

# 打开页面时由浏览器实时检索的新闻源(精选,按重要性排序)
LIVE_TAGS = ["美股", "美股期货", "美国数据", "Fed官员", "特朗普", "芯片/AI", "뉴욕증시", "코스피", "KOSPI", "정책", "환율", "비트코인"]
LIVE_FEEDS = [{"k": f[0], "tag": f[1], "u": f[2], "src": f[3], "h": f[4], "cap": f[5]}
              for tg in LIVE_TAGS for f in FEEDS if f[1] == tg]

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def strip(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()

def tagname(e):
    return e.tag.split("}")[-1]

def parse_feed(data):
    root = ET.fromstring(data)
    out = []
    for it in root.iter():
        if tagname(it) not in ("item", "entry"):
            continue
        d = {}
        for c in it:
            n = tagname(c)
            if n == "link":
                d["link"] = c.get("href") or (c.text or "")
            elif n in ("title", "description", "summary", "pubDate", "published", "updated", "source"):
                d.setdefault(n, c.text or "")
        ds = d.get("pubDate") or d.get("published") or d.get("updated") or ""
        try:
            dt = parsedate_to_datetime(ds)
        except Exception:
            try:
                dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            except Exception:
                dt = None
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out.append({"title": strip(d.get("title")), "link": d.get("link", "").strip(),
                    "desc": strip(d.get("description") or d.get("summary")),
                    "dt": dt, "source": strip(d.get("source"))})
    return out

def nkey(s):
    return re.sub(r"[^a-z0-9가-힣\u4e00-\u9fff]", "", (s or "").lower())[:45]

def has_hangul(s):
    return re.search(r"[\uac00-\ud7a3]", s) is not None

try:
    CACHE = json.load(open(CACHE_FILE, encoding="utf-8"))
except Exception:
    CACHE = {}
USED = {}

def _ok(t, tl):
    if not t or "MYMEMORY" in t.upper():
        return False
    if tl.startswith("zh"):  # 中文:必须含汉字且不含韩文(避免 "美빅테크" 这类混合标题被误判为已是中文)
        return re.search(r"[\u4e00-\u9fff]", t) is not None and not has_hangul(t)
    return has_hangul(t)

def _p_gtx(text, tl):
    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(
        {"client": "gtx", "sl": "auto", "tl": tl, "dt": "t", "q": text})
    res = json.loads(get(url, 20).decode("utf-8"))
    return "".join(seg[0] for seg in res[0] if seg and seg[0])

def _p_chrome(text, tl):
    url = "https://clients5.google.com/translate_a/t?" + urllib.parse.urlencode(
        {"client": "dict-chrome-ex", "sl": "auto", "tl": tl, "q": text})
    res = json.loads(get(url, 20).decode("utf-8"))
    r = res[0] if isinstance(res, list) else res
    return r[0] if isinstance(r, list) else r

def _p_mymemory(text, tl):
    src = "ko" if has_hangul(text) else "en"
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
        {"q": text[:480], "langpair": src + "|" + ("zh-CN" if tl.startswith("zh") else "ko")})
    return json.loads(get(url, 20).decode("utf-8"))["responseData"]["translatedText"]

PROVIDERS = [("gtx", _p_gtx), ("chrome", _p_chrome), ("mymemory", _p_mymemory)]
FAILS = {}

def translate(text, tl):
    """免费翻译,依次尝试多个接口;全部失败则返回原文(网页端会再补翻一次)。"""
    if not text:
        return ""
    key = tl + "|" + hashlib.sha1(text.encode()).hexdigest()
    if key in CACHE:
        USED[key] = CACHE[key]
        return CACHE[key]
    if _ok(text, tl):
        return text
    for name, fn in PROVIDERS:
        try:
            t = (fn(text, tl) or "").strip()
            if _ok(t, tl):
                CACHE[key] = USED[key] = t
                time.sleep(0.25)
                return t
            FAILS[name] = FAILS.get(name, 0) + 1
        except Exception as e:
            FAILS[name] = FAILS.get(name, 0) + 1
            if FAILS[name] <= 2:
                print("translate provider", name, "failed:", e)
    return text

def main():
    now = datetime.now(timezone.utc)
    try:
        PREV = json.load(open(os.path.join(HERE, "docs", "data.json"), encoding="utf-8"))
    except Exception:
        PREV = {}
    items, seen = [], set()
    def load(f):
        for attempt in (1, 2):
            try:
                return parse_feed(get(f[2], 20))
            except Exception as e:
                if attempt == 2:
                    print("feed fail:", f[1], f[2][:60], e)
                else:
                    time.sleep(1.5)
        return None
    with ThreadPoolExecutor(8) as ex:
        loaded = list(ex.map(load, FEEDS))
    for (col, tag, url, fixed, hours, cap), entries in zip(FEEDS, loaded):
        if entries is None:
            continue
        is_gn = "news.google.com" in url
        n = 0
        for e in sorted(entries, key=lambda x: x["dt"] or now, reverse=True):
            if n >= cap:
                break
            if e["dt"] and e["dt"] > now + timedelta(minutes=10):
                # 部分韩国媒体的时间没有时区标记,被当成UTC而显示成"未来":先按韩国时间回拨9小时,仍超前就取当前时间
                sh = e["dt"] - timedelta(hours=9)
                e["dt"] = sh if sh <= now + timedelta(minutes=10) else now
            if e["dt"] and now - e["dt"] > timedelta(hours=hours):
                continue
            title = e["title"]
            src = fixed or e["source"] or tag
            if is_gn and src and title.endswith(" - " + src):
                title = title[: -len(src) - 3]
            if BLOCK_SRC.search(src or "") or BLOCK_TITLE.search(title):
                continue
            if not passes(col, tag, title, e["desc"]):
                continue
            key = re.sub(r"[^a-z0-9가-힣\u4e00-\u9fff]", "", title.lower())[:45]
            if not title:
                continue
            summ = "" if is_gn else e["desc"][:240]
            items.append({"k": col, "tag": tag, "src": src, "url": e["link"] if e["link"].startswith(("http://", "https://")) else "", "title": title,
                          "summ": summ, "dt": (e["dt"] or now)})
            n += 1
    items = cluster(items)
    now = datetime.now(timezone.utc)
    final, cnt = [], dict.fromkeys(MAX, 0)
    jobs, c2 = set(), dict.fromkeys(MAX, 0)
    for it in items:
        if c2[it["k"]] >= MAX[it["k"]]:
            continue
        c2[it["k"]] += 1
        for txt in (it["title"], it["summ"]):
            jobs.add((txt, "zh-CN"))
            if not has_hangul(it["title"]):
                jobs.add((txt, "ko"))
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(lambda j: translate(*j), sorted(jobs)))
    for it in items:
        if cnt[it["k"]] >= MAX[it["k"]]:
            continue
        cnt[it["k"]] += 1
        age = (now - it["dt"]).total_seconds() / 3600
        sc, imp = score_item(it["title"] + " " + it["summ"], it["k"], age)
        n_src = len(it.get("srcs", ())) or 1
        sc += min(3, n_src - 1) + src_bonus(it["src"])
        ko_src = has_hangul(it["title"])
        zh = {"h": translate(it["title"], "zh-CN"), "b": translate(it["summ"], "zh-CN")}
        ko = {"h": it["title"], "b": it["summ"]} if ko_src else {
            "h": translate(it["title"], "ko"), "b": translate(it["summ"], "ko")}
        kl = 1 if (it["k"] != "k" and KR_LINK.search(it["title"] + " " + it["summ"])) else 0
        al = 1 if ALERT_RE.search(it["title"]) else 0
        of = 1 if (OFFICIAL_SRC_RE.search(it["src"] or "") or it["tag"] in OFFICIAL or it["tag"].startswith("韩央行")) else 0
        sc += (2 if kl else 0) + (4 if al else 0) + (3 if of else 0)
        final.append({"of": of, "kl": kl, "al": al, "o": it["title"], "ts": int(it["dt"].timestamp() * 1000), "sc": sc, "imp": imp, "k": it["k"], "tag": it["tag"], "src": it["src"], "url": it["url"], "n": n_src, "srcs": sorted(it.get("srcs", []))[:5],
                      "t": it["dt"].astimezone(KST).strftime("%m/%d %H:%M"), "zh": zh, "ko": ko})
    # 某个源本次抓取失败时,保留它上一次的新闻(48小时内),避免栏目突然变空
    failed = {f[1] for f, e in zip(FEEDS, loaded) if e is None}
    have = {nkey(x["o"]) for x in final}
    now_ms = int(time.time() * 1000)
    for pv in PREV.get("items", []):
        k = nkey(pv.get("o"))
        if pv.get("tag") in failed and k not in have and now_ms - pv.get("ts", 0) < 48 * 36e5 \
                and cnt.get(pv.get("k"), 99) < MAX.get(pv.get("k"), 0):
            final.append(pv); have.add(k); cnt[pv["k"]] += 1
    final.sort(key=lambda x: x["ts"], reverse=True)
    prev_keys = {nkey(pv.get("o")) for pv in PREV.get("items", [])}
    health = {"ok": sum(1 for e in loaded if e is not None), "total": len(FEEDS),
              "new": sum(1 for x in final if nkey(x["o"]) not in prev_keys),
              "fail": sorted({f[1] for f, e in zip(FEEDS, loaded) if e is None})[:20]}
    json.dump(USED, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    market = fetch_market()
    got = {r["s"] for r in market}
    for r in PREV.get("market", []):  # 某个行情本次失败时沿用上一次的数值
        if r["s"] not in got:
            market.append(r)
    order = {m[1]: i for i, m in enumerate(MKT)}
    market.sort(key=lambda r: order.get(r["s"], 99))
    targets = []
    seen_t = set()
    for x in sorted((x for x in final if x["k"] == "v"), key=lambda x: x["ts"], reverse=True):
        tg = extract_target(x["o"], x["tag"])
        key = tg and (tg["who"], tg["idx"], tg["num"])
        if tg and key not in seen_t:
            seen_t.add(key)
            targets.append(dict(tg, t=x["t"], ts=x["ts"], src=x["src"], url=x["url"], zh={"h": x["zh"]["h"]}, ko={"h": x["ko"]["h"]}))
    payload = ({"updated": stamp, "targets": targets[:12], "officialre": OFFICIAL_SRC_RE.pattern, "krlink": KR_LINK.pattern, "alertre": ALERT_RE.pattern, "items": final, "market": market, "cal": CAL, "kimchi": fetch_kimchi(market),
                       "built": int(time.time() * 1000), "health": health, "kw": KW, "impact": IMPACT, "feeds": LIVE_FEEDS})
    os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
    open(os.path.join(HERE, "docs", "data.json"), "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False))
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    page = open(os.path.join(HERE, "template.html"), encoding="utf-8").read().replace("__DATA__", data)
    os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
    open(os.path.join(HERE, "docs", "index.html"), "w", encoding="utf-8").write(page)
    print("done:", len(final), "items", cnt, "feeds", health, "translate_fails", FAILS, "quotes", len(market))

if __name__ == "__main__":
    main()
