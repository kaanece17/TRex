from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime
import re
import time
import unicodedata
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
import warnings

from bs4 import BeautifulSoup
import pandas as pd
import requests
from urllib3.exceptions import InsecureRequestWarning


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

FINANCIAL_KEYWORDS = (
    "finansal",
    "mali",
    "tablo",
    "dipnot",
    "spk rapor",
    "bağımsız denetim raporu",
    "bagimsiz denetim raporu",
    "psbf",
)
TURKISH_MONTH_TO_QUARTER_END = {
    "mart": 3,
    "haziran": 6,
    "eylul": 9,
    "eylül": 9,
    "aralik": 12,
    "aralık": 12,
}


@dataclass(frozen=True)
class IssuerIRSourceConfig:
    symbol: str
    page_url: str
    extra_page_urls: tuple[str, ...] = ()
    year_param: bool = False
    first_year: int | None = None
    year_param_name: str = "year"
    document_keywords: tuple[str, ...] = FINANCIAL_KEYWORDS
    verify_ssl: bool = True
    max_publication_lag_days: int | None = None


ISSUER_IR_SOURCES: dict[str, IssuerIRSourceConfig] = {
    "FADE": IssuerIRSourceConfig(
        symbol="FADE",
        page_url="https://www.fadegida.com.tr/yatirimci.html",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu", "rapor"),
    ),
    "EUREN": IssuerIRSourceConfig(
        symbol="EUREN",
        page_url="https://yatirimciiliskileri.europen.com.tr/yatirimci-iliskileri/finansal-raporlar",
    ),
    "POLTK": IssuerIRSourceConfig(
        symbol="POLTK",
        page_url="https://www.pm.com.tr/tr-tr/investor-relations/72/finansal-raporlar",
    ),
    "DAGI": IssuerIRSourceConfig(
        symbol="DAGI",
        page_url="https://www.dagi.com.tr/pages/yatirimci-iliskileri",
    ),
    "DGNMO": IssuerIRSourceConfig(
        symbol="DGNMO",
        page_url="https://financialreports.eu/companies/doganlar-mobilya-grubu-imalat-sanayi-ve-ticaret-as/2026/",
    ),
    "DOKTA": IssuerIRSourceConfig(
        symbol="DOKTA",
        page_url="https://financialreports.eu/companies/doktas-dokumculuk-ticaret-ve-sanayi-as/2026/",
    ),
    "GUBRF": IssuerIRSourceConfig(
        symbol="GUBRF",
        page_url="https://www.gubretas.com.tr/tr/yatirimci-iliskileri/finansal-raporlar",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        verify_ssl=False,
    ),
    "SEYKM": IssuerIRSourceConfig(
        symbol="SEYKM",
        page_url="https://www.seyitler.com/investors",
        document_keywords=FINANCIAL_KEYWORDS + ("bağımsız denetim raporu", "bagimsiz denetim raporu"),
        verify_ssl=False,
    ),
    "GIPTA": IssuerIRSourceConfig(
        symbol="GIPTA",
        page_url="https://financialreports.eu/companies/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/2024/",
    ),
    "GUNDG": IssuerIRSourceConfig(
        symbol="GUNDG",
        page_url="https://financialreports.eu/companies/gundogdu-gida-sut-urunleri-sanayi-ve-dis-ticaret-as/2025/",
    ),
    "SNICA": IssuerIRSourceConfig(
        symbol="SNICA",
        page_url="https://financialreports.eu/companies/sanica-isi-sanayi-as/2025/",
    ),
    "TATGD": IssuerIRSourceConfig(
        symbol="TATGD",
        page_url="https://financialreports.eu/companies/tat-gida-sanayi-as/2020/",
    ),
    "DOFER": IssuerIRSourceConfig(
        symbol="DOFER",
        page_url="https://financialreports.eu/companies/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/2024/",
    ),
    "AGROT": IssuerIRSourceConfig(
        symbol="AGROT",
        page_url="https://financialreports.eu/companies/agrotech-yuksek-teknoloji-ve-yatirim-as/2024/",
    ),
    "ALKA": IssuerIRSourceConfig(
        symbol="ALKA",
        page_url="https://financialreports.eu/companies/alkim-kagit-sanayi-ve-ticaret-as/2026/",
    ),
    "EKOS": IssuerIRSourceConfig(
        symbol="EKOS",
        page_url="https://financialreports.eu/companies/ekos-teknoloji-ve-elektrik-as/2024/",
    ),
    "MEGMT": IssuerIRSourceConfig(
        symbol="MEGMT",
        page_url="https://financialreports.eu/companies/mega-metal-sanayi-ve-ticaret-as/2024/",
    ),
    "MEKAG": IssuerIRSourceConfig(
        symbol="MEKAG",
        page_url="https://financialreports.eu/companies/meka-global-makine-imalat-sanayi-ve-ticaret-as/2024/",
    ),
    "KBORU": IssuerIRSourceConfig(
        symbol="KBORU",
        page_url="https://financialreports.eu/companies/kuzey-boru-as/2024/",
    ),
    "PETUN": IssuerIRSourceConfig(
        symbol="PETUN",
        page_url="https://www.vkyanaliz.com/rap/PETUN_2026-05-05_40256.pdf",
    ),
    "FMIZP": IssuerIRSourceConfig(
        symbol="FMIZP",
        page_url="https://www.vkyanaliz.com/rap/FMIZP_2026-05-04_39574.pdf",
    ),
    "BRKSN": IssuerIRSourceConfig(
        symbol="BRKSN",
        page_url="https://financialreports.eu/companies/berkosan-yalitim-ve-tecrit-maddeleri-uretim-ve-ticaret-as/2024/",
    ),
    "DMRGD": IssuerIRSourceConfig(
        symbol="DMRGD",
        page_url="https://financialreports.eu/companies/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/2024/",
    ),
    "OFSYM": IssuerIRSourceConfig(
        symbol="OFSYM",
        page_url="https://financialreports.eu/companies/ofis-yem-gida-sanayi-ticaret-as/2024/",
    ),
    "KONKA": IssuerIRSourceConfig(
        symbol="KONKA",
        page_url="https://financialreports.eu/companies/konya-kagit-sanayi-ve-ticaret-as/2024/",
    ),
    "KLSER": IssuerIRSourceConfig(
        symbol="KLSER",
        page_url="https://financialreports.eu/companies/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/2024/",
    ),
    "HATSN": IssuerIRSourceConfig(
        symbol="HATSN",
        page_url="https://financialreports.eu/companies/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/2024/",
    ),
    "TARKM": IssuerIRSourceConfig(
        symbol="TARKM",
        page_url="https://financialreports.eu/companies/tarkim-bitki-koruma-sanayi-ve-ticaret-as/2024/",
    ),
    "MAKIM": IssuerIRSourceConfig(
        symbol="MAKIM",
        page_url="https://financialreports.eu/companies/makim-makina-teknolojileri-sanayi-ve-ticaret-as/2024/",
    ),
    "EUPWR": IssuerIRSourceConfig(
        symbol="EUPWR",
        page_url="https://financialreports.eu/companies/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/2024/",
    ),
    "ALVES": IssuerIRSourceConfig(
        symbol="ALVES",
        page_url="https://financialreports.eu/companies/alves-kablo-sanayi-ve-ticaret-as/2024/",
    ),
    "ARTMS": IssuerIRSourceConfig(
        symbol="ARTMS",
        page_url="https://financialreports.eu/companies/artemis-hali-as/2024/",
    ),
    "LMKDC": IssuerIRSourceConfig(
        symbol="LMKDC",
        page_url="https://financialreports.eu/companies/limak-dogu-anadolu-cimento-sanayi-ve-ticaret-as/2024/",
    ),
    "CEMAS": IssuerIRSourceConfig(
        symbol="CEMAS",
        page_url="https://cemas.com.tr/yatirimci.php?lang=tr&p=mali-tablolar",
    ),
    "BESLR": IssuerIRSourceConfig(
        symbol="BESLR",
        page_url="https://www.besler.com.tr/tr/yatirimci-iliskileri/mali-tablolar",
        year_param=True,
        first_year=2019,
    ),
    "BNTAS": IssuerIRSourceConfig(
        symbol="BNTAS",
        page_url="https://www.bantas.com.tr/faaliyet-raporlari/",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
    ),
    "ENSRI": IssuerIRSourceConfig(
        symbol="ENSRI",
        page_url="https://www.ensariyatirimlar.com/en/documents/financial-statements-16.html",
    ),
    "IZFAS": IssuerIRSourceConfig(
        symbol="IZFAS",
        page_url="https://www.izmirfirca.com.tr/yatirimci-iliskileri/",
    ),
    "IZINV": IssuerIRSourceConfig(
        symbol="IZINV",
        page_url="https://www.izyatirimholding.com/financialdata?lang=tr",
        document_keywords=FINANCIAL_KEYWORDS + ("finansal rapor",),
    ),
    "TRILC": IssuerIRSourceConfig(
        symbol="TRILC",
        page_url="https://www.turkilac.com.tr/tr/raporlar.php",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu", "bağımsız denetim raporu", "bagimsiz denetim raporu"),
    ),
    "DITAS": IssuerIRSourceConfig(
        symbol="DITAS",
        page_url="https://www.ditas.com.tr/yatirimci-iliskileri-raporlar-ve-sunumlar",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu", "rapor"),
    ),
    "AVOD": IssuerIRSourceConfig(
        symbol="AVOD",
        page_url="https://avod.com.tr/yatirimci-iliskileri/",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu", "rapor"),
        verify_ssl=False,
    ),
    "BLCYT": IssuerIRSourceConfig(
        symbol="BLCYT",
        page_url="https://www.biliciyatirim.com/mali-tablolar",
        year_param=True,
        first_year=2019,
        year_param_name="yil",
        verify_ssl=False,
    ),
    "BMSCH": IssuerIRSourceConfig(
        symbol="BMSCH",
        page_url="https://www.bmstel.com.tr/mali-tablolar/",
    ),
    "MNDRS": IssuerIRSourceConfig(
        symbol="MNDRS",
        page_url="https://www.menderes.com/tr/yatirimci-iliskileri/finansal-raporlar/ara-donem-finansal-raporlar",
        extra_page_urls=(
            "https://www.menderes.com/tr/yatirimci-iliskileri/finansal-raporlar/yillik-finansal-raporlar",
        ),
    ),
    "FRIGO": IssuerIRSourceConfig(
        symbol="FRIGO",
        page_url="https://www.frigo-pak.com.tr/finansal-raporlar/",
        verify_ssl=False,
    ),
    "DESA": IssuerIRSourceConfig(
        symbol="DESA",
        page_url="https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6720158/",
    ),
    "PRZMA": IssuerIRSourceConfig(
        symbol="PRZMA",
        page_url="https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6719910/",
    ),
    "BRISA": IssuerIRSourceConfig(
        symbol="BRISA",
        page_url="https://www.brisa.com.tr/yatirimci-iliskileri/sunumlar-ve-raporlar/finansal-tablolar-ve-bagimsiz-denetci-raporu/",
        verify_ssl=False,
    ),
    "KUTPO": IssuerIRSourceConfig(
        symbol="KUTPO",
        page_url="https://kurumsal.kutahyaporselen.com/tr/yatirimci-iliskileri/periyodik-mali-tablo-ve-raporlar",
        verify_ssl=False,
    ),
    "KRSTL": IssuerIRSourceConfig(
        symbol="KRSTL",
        page_url="https://kristalkola.com.tr/dokumanlar/mali-tablolar/2023/03/",
        extra_page_urls=(
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2023/06/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2023/09/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2023/12/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2024/03/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2024/06/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2024/09/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2024/12/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2025/03/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2025/06/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2025/09/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2025/12/",
            "https://kristalkola.com.tr/dokumanlar/mali-tablolar/2026/03/",
        ),
        verify_ssl=False,
    ),
    "SELVA": IssuerIRSourceConfig(
        symbol="SELVA",
        page_url="https://www.selva.com.tr/Tr/Sayfalar/Finansal-Veriler/44",
        verify_ssl=False,
    ),
    "HATEK": IssuerIRSourceConfig(
        symbol="HATEK",
        page_url="https://www.hateks.com.tr/yatirimci",
        max_publication_lag_days=180,
    ),
    "HKTM": IssuerIRSourceConfig(
        symbol="HKTM",
        page_url="https://financialreports.eu/filings/hidropar-hareket-kontrol-teknolojileri-merkezi-sanayi-ve-ticaret-as/audit-report-information/2024/6661795/",
    ),
    "IMASM": IssuerIRSourceConfig(
        symbol="IMASM",
        page_url="https://financialreports.eu/filings/imas-makina-sanayi-as/report-publication-announcement/2024/6626690/",
    ),
    "ACSEL": IssuerIRSourceConfig(
        symbol="ACSEL",
        page_url="https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6721056/",
    ),
    "BLUME": IssuerIRSourceConfig(
        symbol="BLUME",
        page_url="https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2023/6717872/",
    ),
    "BURCE": IssuerIRSourceConfig(
        symbol="BURCE",
        page_url="https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2023/6715537/",
    ),
    "BURVA": IssuerIRSourceConfig(
        symbol="BURVA",
        page_url="https://financialreports.eu/filings/burcelik-vana-sanayi-ve-ticaret-as/report-publication-announcement/2023/6718973/",
    ),
    "KOPOL": IssuerIRSourceConfig(
        symbol="KOPOL",
        page_url="https://financialreports.eu/filings/koza-polyester-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6718876/",
    ),
    "DARDL": IssuerIRSourceConfig(
        symbol="DARDL",
        page_url="https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/annual-quarterly-financial-statement/2023/6736161/",
    ),
    "CUSAN": IssuerIRSourceConfig(
        symbol="CUSAN",
        page_url="https://financialreports.eu/filings/6735985/content/",
    ),
    "DNISI": IssuerIRSourceConfig(
        symbol="DNISI",
        page_url="https://financialreports.eu/filings/6721009/content/",
    ),
    "DOGUB": IssuerIRSourceConfig(
        symbol="DOGUB",
        page_url="https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/business-and-financial-review/2023/6719811/",
    ),
    "EGGUB": IssuerIRSourceConfig(
        symbol="EGGUB",
        page_url="https://financialreports.eu/filings/ege-gubre-sanayii-as/regulatory-filings/2026/35683644/",
    ),
    "EGSER": IssuerIRSourceConfig(
        symbol="EGSER",
        page_url="https://financialreports.eu/filings/ege-seramik-sanayi-ve-ticaret-as/regulatory-filings/2026/35271483/",
    ),
    "EGPRO": IssuerIRSourceConfig(
        symbol="EGPRO",
        page_url="https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2023/6714471/",
    ),
    "FORMT": IssuerIRSourceConfig(
        symbol="FORMT",
        page_url="https://financialreports.eu/filings/formet-metal-ve-cam-sanayi-as/report-publication-announcement/2023/6725953/",
    ),
    "JANTS": IssuerIRSourceConfig(
        symbol="JANTS",
        page_url="https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6712574/",
    ),
    "GEREL": IssuerIRSourceConfig(
        symbol="GEREL",
        page_url="https://financialreports.eu/filings/6716635/content/",
    ),
    "KARTN": IssuerIRSourceConfig(
        symbol="KARTN",
        page_url="https://financialreports.eu/filings/kartonsan-karton-sanayi-ve-ticaret-as/annual-report/2024/6665375/",
    ),
    "LUKSK": IssuerIRSourceConfig(
        symbol="LUKSK",
        page_url="https://financialreports.eu/filings/6700873/content/",
    ),
    "MERCN": IssuerIRSourceConfig(
        symbol="MERCN",
        page_url="https://financialreports.eu/filings/9096/2024/RNS/9096_rns_2024-11-11_85e9dfef-7217-43a6-a410-b4573c4b1fc6.html",
    ),
    "MERKO": IssuerIRSourceConfig(
        symbol="MERKO",
        page_url="https://financialreports.eu/filings/merko-gida-sanayi-ve-ticaret-as/audit-report-information/2023/6736589/",
    ),
    "MRSHL": IssuerIRSourceConfig(
        symbol="MRSHL",
        page_url="https://financialreports.eu/filings/marshall-boya-ve-vernik-sanayii-as/report-publication-announcement/2023/6720785/",
    ),
    "SAMAT": IssuerIRSourceConfig(
        symbol="SAMAT",
        page_url="https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2023/6719858/",
    ),
    "SARKY": IssuerIRSourceConfig(
        symbol="SARKY",
        page_url="https://financialreports.eu/filings/sarkuysan-elektrolitik-bakir-sanayi-ve-ticaret-as/report-publication-announcement/2023/6715002/",
    ),
    "SAYAS": IssuerIRSourceConfig(
        symbol="SAYAS",
        page_url="https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6702104/",
    ),
    "SNICA": IssuerIRSourceConfig(
        symbol="SNICA",
        page_url="https://financialreports.eu/companies/sanica-isi-sanayi-as/2025/",
    ),
    "RTALB": IssuerIRSourceConfig(
        symbol="RTALB",
        page_url="https://financialreports.eu/filings/rta-laboratuvarlari-biyolojik-urunler-ilac-ve-makine-sanayi-ticaret-as/report-publication-announcement/2023/6719358/",
    ),
    "YKSLN": IssuerIRSourceConfig(
        symbol="YKSLN",
        page_url="https://financialreports.eu/filings/yukselen-celik-as/report-publication-announcement/2023/6719258/",
    ),
    "OYLUM": IssuerIRSourceConfig(
        symbol="OYLUM",
        page_url="https://www.oylum.com/finansal-raporlar/",
    ),
    "OZSUB": IssuerIRSourceConfig(
        symbol="OZSUB",
        page_url="https://ozsubalik.com.tr/finansal-tablo-ve-raporlar/",
    ),
    "OYAKC": IssuerIRSourceConfig(
        symbol="OYAKC",
        page_url="https://financialreports.eu/companies/oyak-cimento-fabrikalar-as/",
    ),
    "BANVT": IssuerIRSourceConfig(
        symbol="BANVT",
        page_url="https://www.banvit.com/kurumsal/donemsel-raporlar",
    ),
    "TBORG": IssuerIRSourceConfig(
        symbol="TBORG",
        page_url="https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/report-publication-announcement/2024/6615827/",
    ),
    "BFREN": IssuerIRSourceConfig(
        symbol="BFREN",
        page_url="https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6625381/",
    ),
    "OZRDN": IssuerIRSourceConfig(
        symbol="OZRDN",
        page_url="https://financialreports.eu/companies/ozerden-ambalaj-sanayi-as/2020/",
    ),
    "ULUUN": IssuerIRSourceConfig(
        symbol="ULUUN",
        page_url="https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6701746/",
    ),
    "OBAMS": IssuerIRSourceConfig(
        symbol="OBAMS",
        page_url="https://financialreports.eu/companies/oba-makarnacilik-sanayi-ve-ticaret-as/2024/",
    ),
    "YAPRK": IssuerIRSourceConfig(
        symbol="YAPRK",
        page_url="https://financialreports.eu/filings/6627597/content/",
    ),
    "YUNSA": IssuerIRSourceConfig(
        symbol="YUNSA",
        page_url="https://financialreports.eu/filings/yunsa-yunlu-sanayi-ve-ticaret-as/regulatory-filings/2026/34659872/",
    ),
    "TUKAS": IssuerIRSourceConfig(
        symbol="TUKAS",
        page_url="https://financialreports.eu/filings/tukas-gda-sanayi-ve-ticaret-as/interim-report/2024/6628304/",
    ),
    "TUCLK": IssuerIRSourceConfig(
        symbol="TUCLK",
        page_url="https://www.tugcelik.com.tr/tr/finansal-tablolar/",
    ),
    "MAKTK": IssuerIRSourceConfig(
        symbol="MAKTK",
        page_url="https://makinatakim.com.tr/yatirimci-iliskileri/mali-raporlar-ve-dipnotlar/",
    ),
    "SAFKR": IssuerIRSourceConfig(
        symbol="SAFKR",
        page_url="https://www.safkar.com.tr/yatirimci-iliskileri/",
        verify_ssl=False,
    ),
    "SANFM": IssuerIRSourceConfig(
        symbol="SANFM",
        page_url="https://www.sanifoam.com.tr/yatirimci-iliskileri",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=180,
    ),
    "SEKUR": IssuerIRSourceConfig(
        symbol="SEKUR",
        page_url="https://www.sekuro.com.tr/tr/yatirimci-iliskileri",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=180,
    ),
    "EKSUN": IssuerIRSourceConfig(
        symbol="EKSUN",
        page_url="https://www.eksun.com.tr/yatirimci-iliskileri/finansal-raporlar-ve-sunumlar",
        verify_ssl=False,
    ),
    "CVKMD": IssuerIRSourceConfig(
        symbol="CVKMD",
        page_url="https://www.cvkmadencilik.com/yatirimci-iliskileri/finansal-raporlar",
        verify_ssl=False,
    ),
    "BIENY": IssuerIRSourceConfig(
        symbol="BIENY",
        page_url="https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2023/6728459/",
        extra_page_urls=(
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2023/6715000/",
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2023/6700939/",
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6660739/",
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6647696/",
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6623222/",
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6614285/",
        ),
    ),
    "RUBNS": IssuerIRSourceConfig(
        symbol="RUBNS",
        page_url="https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2023/6719612/",
        extra_page_urls=(
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2023/6703889/",
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6670855/",
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6655697/",
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6626593/",
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6617753/",
        ),
    ),
    "KLSYN": IssuerIRSourceConfig(
        symbol="KLSYN",
        page_url="https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2023/6736316/",
        extra_page_urls=(
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2023/6715640/",
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2023/6702127/",
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2024/6659919/",
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2024/6650259/",
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/interim-quarterly-report/2024/6624322/",
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2024/6616108/",
        ),
    ),
    "ASTOR": IssuerIRSourceConfig(
        symbol="ASTOR",
        page_url="https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2023/6719327/",
        extra_page_urls=(
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2023/6703549/",
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6682368/",
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6657125/",
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6632006/",
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6617944/",
        ),
    ),
    "SOKE": IssuerIRSourceConfig(
        symbol="SOKE",
        page_url="https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6716316/",
        extra_page_urls=(
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701739/",
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6660945/",
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6649362/",
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6624161/",
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615337/",
        ),
    ),
    "ORCAY": IssuerIRSourceConfig(
        symbol="ORCAY",
        page_url="https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2023/6738122/",
        extra_page_urls=(
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2023/6718383/",
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701516/",
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6668629/",
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6651974/",
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6631022/",
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6618585/",
        ),
    ),
    "BARMA": IssuerIRSourceConfig(
        symbol="BARMA",
        page_url="https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6740089/",
        extra_page_urls=(
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6719904/",
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6705060/",
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6757948/",
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6651443/",
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6625397/",
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615554/",
        ),
    ),
    "BAYRK": IssuerIRSourceConfig(
        symbol="BAYRK",
        page_url="https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2023/6733814/",
        extra_page_urls=(
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6720153/",
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/report-publication-announcement/2023/6706360/",
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/audit-report-information/2024/6671514/",
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650996/",
            "https://financialreports.eu/filings/6627967/content/",
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/report-publication-announcement/2024/6611393/",
        ),
    ),
    "ANGEN": IssuerIRSourceConfig(
        symbol="ANGEN",
        page_url="https://financialreports.eu/filings/anatolia-tani-ve-biyoteknoloji-urunleri-arastirma-gelistirme-sanayi-ve-ticaret-as/environmental-social-information/2023/6717458/",
        extra_page_urls=(
            "https://financialreports.eu/filings/anatolia-tani-ve-biyoteknoloji-urunleri-arastirma-gelistirme-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6702846/",
            "https://financialreports.eu/filings/6663320/content/",
            "https://financialreports.eu/filings/6649346/content/",
            "https://financialreports.eu/filings/6625212/content/",
            "https://financialreports.eu/filings/anatolia-tani-ve-biyoteknoloji-urunleri-arastirma-gelistirme-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6615182/",
        ),
    ),
    "BMSTL": IssuerIRSourceConfig(
        symbol="BMSTL",
        page_url="https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6720248/",
        extra_page_urls=(
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6698120/",
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/report-publication-announcement/2024/6674891/",
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6655248/",
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6624971/",
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/earnings-release/2024/6615416/",
        ),
    ),
    "YYLGD": IssuerIRSourceConfig(
        symbol="YYLGD",
        page_url="https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6734516/",
        extra_page_urls=(
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6719711/",
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6705747/",
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6666007/",
            "https://financialreports.eu/filings/6662132/content/",
            "https://financialreports.eu/filings/6627740/content/",
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6621683/",
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2026/8243505/",
        ),
    ),
    "PNLSN": IssuerIRSourceConfig(
        symbol="PNLSN",
        page_url="https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6721796/",
        extra_page_urls=(
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704832/",
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6673821/",
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6650834/",
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6626542/",
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6617578/",
        ),
    ),
    "KAYSE": IssuerIRSourceConfig(
        symbol="KAYSE",
        page_url="https://www.kayseriseker.com.tr/YatirimciIliskileri/_Belgeler/11",
        verify_ssl=False,
    ),
    "TEZOL": IssuerIRSourceConfig(
        symbol="TEZOL",
        page_url="https://www.tezol.com.tr/finansalbilgiler/",
        extra_page_urls=(
            "https://www.tezol.com.tr/faaliyet-raporlari/",
        ),
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        verify_ssl=False,
        max_publication_lag_days=180,
    ),
    "VANGD": IssuerIRSourceConfig(
        symbol="VANGD",
        page_url="https://www.vanet.com.tr/investor/financialstatements",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        verify_ssl=False,
        max_publication_lag_days=180,
    ),
    "BVSAN": IssuerIRSourceConfig(
        symbol="BVSAN",
        page_url="https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/report-publication-announcement/2023/6736472/",
        extra_page_urls=(
            "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/audit-report-information/2023/6716212/",
            "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701130/",
            "https://financialreports.eu/filings/6661390/content/",
            "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6647255/",
            "https://financialreports.eu/filings/6624692/content/",
            "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6613364/",
            "https://financialreports.eu/filings/bulbuloglu-vinc-sanayi-ve-ticaret-as/interim-quarterly-report/2026/46106082/",
        ),
    ),
    "PRKME": IssuerIRSourceConfig(
        symbol="PRKME",
        page_url="https://financialreports.eu/filings/park-elektrik-uretim-madencilik-sanayi-ve-ticaret-as/interim-report/2023/6737052/",
        extra_page_urls=(
            "https://financialreports.eu/filings/park-elektrik-uretim-madencilik-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6716852/",
            "https://financialreports.eu/filings/6669363/content/",
            "https://financialreports.eu/filings/6669365/content/",
            "https://financialreports.eu/filings/6657867/content/",
            "https://financialreports.eu/filings/6628440/content/",
            "https://financialreports.eu/filings/6615464/content/",
        ),
    ),
    "RUZYE": IssuerIRSourceConfig(
        symbol="RUZYE",
        page_url="https://ruzymadencilik.com.tr/yatirimci-iliskileri/finansal-tablolar-ve-bagimsiz-denetim-raporlari/",
        verify_ssl=False,
        max_publication_lag_days=120,
    ),
    "RNPOL": IssuerIRSourceConfig(
        symbol="RNPOL",
        page_url="https://rainbowpc.com.tr/sayfa/raporlar",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=120,
    ),
    "RODRG": IssuerIRSourceConfig(
        symbol="RODRG",
        page_url="https://rodrigo.com.tr/pages/finansal-tablolar",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=180,
    ),
    "GEDZA": IssuerIRSourceConfig(
        symbol="GEDZA",
        page_url="https://gedizambalaj.com/pages/yatirimci",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=180,
    ),
    "DURDO": IssuerIRSourceConfig(
        symbol="DURDO",
        page_url="https://www.durukan.com.tr/faaliyet-raporlari/",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=180,
    ),
    "TMPOL": IssuerIRSourceConfig(
        symbol="TMPOL",
        page_url="https://www.temapol.com.tr/tr/i-39/yatirimci-iliskileri/finansal-tablo-dipnot-aciklamalari",
        extra_page_urls=(
            "https://www.temapol.com.tr/tr/i-14/yatirimci-iliskileri/faaliyet-raporlari",
        ),
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        verify_ssl=False,
        max_publication_lag_days=180,
    ),
    "GOKNR": IssuerIRSourceConfig(
        symbol="GOKNR",
        page_url="https://www.goknur.com.tr/sayfa/finansal-tablolar",
        extra_page_urls=(
            "https://www.goknur.com.tr/sayfa/faaliyet-raporlari",
        ),
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=180,
    ),
    "MARBL": IssuerIRSourceConfig(
        symbol="MARBL",
        page_url="https://www.marblesystemstureks.com.tr/yatirimci-iliskileri/finansal-tablolar/",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=180,
    ),
    "RTALB": IssuerIRSourceConfig(
        symbol="RTALB",
        page_url="https://www.rtalabs.com.tr/yatirimci-iliskileri/ozel-durum-aciklamalari",
        extra_page_urls=(
            "https://www.rtalabs.com.tr/yatirimci-iliskileri/finansal-raporlar",
        ),
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=180,
    ),
    "NIBAS": IssuerIRSourceConfig(
        symbol="NIBAS",
        page_url="https://www.nigbas.com.tr/yatirimci.php?lang=&p=mali-tablo-ve-raporlar",
        extra_page_urls=(
            "https://www.nigbas.com.tr/yatirimci.php?lang=&p=faaliyet-raporlari",
        ),
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=180,
    ),
    "KRPLS": IssuerIRSourceConfig(
        symbol="KRPLS",
        page_url="https://www.koroplast.com/sayfa/yatirimci-iliskileri",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu",),
        max_publication_lag_days=180,
    ),
    "SILVR": IssuerIRSourceConfig(
        symbol="SILVR",
        page_url="https://financialreports.eu/companies/silverline-endustri-ve-ticaret-as/",
    ),
    "ONCSM": IssuerIRSourceConfig(
        symbol="ONCSM",
        page_url="https://financialreports.eu/companies/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/",
    ),
    "KTSKR": IssuerIRSourceConfig(
        symbol="KTSKR",
        page_url="https://kutahyaseker.com.tr/finansrapor.html",
        document_keywords=FINANCIAL_KEYWORDS + ("faaliyet raporu", "rapor"),
        verify_ssl=False,
        max_publication_lag_days=180,
    ),
    "ISKPL": IssuerIRSourceConfig(
        symbol="ISKPL",
        page_url="https://financialreports.eu/companies/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/",
    ),
    "ELITE": IssuerIRSourceConfig(
        symbol="ELITE",
        page_url="https://financialreports.eu/companies/elite-naturel-organik-gida-sanayi-ve-ticaret-as/",
    ),
    "ERCB": IssuerIRSourceConfig(
        symbol="ERCB",
        page_url="https://financialreports.eu/companies/erciyas-celik-boru-sanayi-as/",
    ),
    "ISSEN": IssuerIRSourceConfig(
        symbol="ISSEN",
        page_url="https://financialreports.eu/companies/isbir-sentetik-dokuma-sanayi-as/",
    ),
    "OZYSR": IssuerIRSourceConfig(
        symbol="OZYSR",
        page_url="https://financialreports.eu/companies/ozyasar-tel/",
    ),
}


class IssuerIRAnnouncementsLoader:
    def __init__(
        self,
        request_timeout_seconds: int = 20,
        min_request_interval_seconds: float = 0.2,
    ) -> None:
        self.request_timeout_seconds = request_timeout_seconds
        self.min_request_interval_seconds = min_request_interval_seconds
        self._last_request_monotonic = 0.0

    def fetch_records(self, symbol: str) -> list[dict]:
        symbol_upper = symbol.upper()
        config = ISSUER_IR_SOURCES.get(symbol_upper)
        if config is None:
            raise ValueError(f"issuer ir fallback is not configured for symbol: {symbol_upper}")
        if symbol_upper == "HATEK":
            return self._fetch_hatek_records(symbol_upper, config)
        if symbol_upper == "HKTM":
            return self._fetch_hktm_records(symbol_upper)
        if symbol_upper == "IMASM":
            return self._fetch_imasm_records(symbol_upper)
        if symbol_upper == "BMSCH":
            return self._fetch_bmsch_records(symbol_upper)
        if symbol_upper == "MARBL":
            return self._fetch_marbl_records(symbol_upper)
        if symbol_upper == "OBAMS":
            return self._fetch_obams_records(symbol_upper)
        if symbol_upper == "ALVES":
            return self._fetch_alves_records(symbol_upper)
        if symbol_upper == "ARTMS":
            return self._fetch_artms_records(symbol_upper)
        if symbol_upper == "LMKDC":
            return self._fetch_lmkdc_records(symbol_upper)
        if symbol_upper == "ACSEL":
            return self._fetch_acsel_records(symbol_upper)
        if symbol_upper == "BLUME":
            return self._fetch_blume_records(symbol_upper)
        if symbol_upper == "BURCE":
            return self._fetch_burce_records(symbol_upper)
        if symbol_upper == "BURVA":
            return self._fetch_burva_records(symbol_upper)
        if symbol_upper == "KOPOL":
            return self._fetch_kopol_records(symbol_upper)
        if symbol_upper == "DARDL":
            return self._fetch_dardl_records(symbol_upper)
        if symbol_upper == "DOKTA":
            return self._fetch_dokta_records(symbol_upper)
        if symbol_upper == "DAGI":
            return self._fetch_dagi_records(symbol_upper)
        if symbol_upper == "DGNMO":
            return self._fetch_dgnmo_records(symbol_upper)
        if symbol_upper == "CUSAN":
            return self._fetch_cusan_records(symbol_upper)
        if symbol_upper == "DNISI":
            return self._fetch_dnisi_records(symbol_upper)
        if symbol_upper == "DOGUB":
            return self._fetch_dogub_records(symbol_upper)
        if symbol_upper == "EGGUB":
            return self._fetch_eggub_records(symbol_upper)
        if symbol_upper == "EGSER":
            return self._fetch_egser_records(symbol_upper)
        if symbol_upper == "FRIGO":
            return self._fetch_frigo_records(symbol_upper)
        if symbol_upper == "DESA":
            return self._fetch_desa_records(symbol_upper)
        if symbol_upper == "PRZMA":
            return self._fetch_przma_records(symbol_upper)
        if symbol_upper == "EGPRO":
            return self._fetch_egpro_records(symbol_upper)
        if symbol_upper == "FORMT":
            return self._fetch_formt_records(symbol_upper)
        if symbol_upper == "JANTS":
            return self._fetch_jants_records(symbol_upper)
        if symbol_upper == "GEREL":
            return self._fetch_gerel_records(symbol_upper)
        if symbol_upper == "OZYSR":
            return self._fetch_ozysr_records(symbol_upper)
        if symbol_upper == "KARTN":
            return self._fetch_kartn_records(symbol_upper)
        if symbol_upper == "LUKSK":
            return self._fetch_luksk_records(symbol_upper)
        if symbol_upper == "MERCN":
            return self._fetch_mercn_records(symbol_upper)
        if symbol_upper == "MERKO":
            return self._fetch_merko_records(symbol_upper)
        if symbol_upper == "MRSHL":
            return self._fetch_mrshl_records(symbol_upper)
        if symbol_upper == "SAMAT":
            return self._fetch_samat_records(symbol_upper)
        if symbol_upper == "SARKY":
            return self._fetch_sarky_records(symbol_upper)
        if symbol_upper == "SAYAS":
            return self._fetch_sayas_records(symbol_upper)
        if symbol_upper == "SNICA":
            return self._fetch_snica_records(symbol_upper)
        if symbol_upper == "RTALB":
            return self._fetch_rtalb_records(symbol_upper)
        if symbol_upper == "YKSLN":
            return self._fetch_yksln_records(symbol_upper)
        if symbol_upper == "OYLUM":
            return self._fetch_oylum_records(symbol_upper)
        if symbol_upper == "OZSUB":
            return self._fetch_ozsub_records(symbol_upper)
        if symbol_upper == "OYAKC":
            return self._fetch_oyakc_records(symbol_upper)
        if symbol_upper == "BANVT":
            return self._fetch_banvt_records(symbol_upper)
        if symbol_upper == "BNTAS":
            return self._fetch_bntas_records(symbol_upper)
        if symbol_upper == "TBORG":
            return self._fetch_tborg_records(symbol_upper)
        if symbol_upper == "BFREN":
            return self._fetch_bfren_records(symbol_upper)
        if symbol_upper == "OZRDN":
            return self._fetch_ozrdn_records(symbol_upper)
        if symbol_upper == "ULUUN":
            return self._fetch_uluun_records(symbol_upper)
        if symbol_upper == "TEZOL":
            return self._fetch_tezol_records(symbol_upper)
        if symbol_upper == "YAPRK":
            return self._fetch_yaprk_records(symbol_upper)
        if symbol_upper == "YUNSA":
            return self._fetch_yunsa_records(symbol_upper)
        if symbol_upper == "TUKAS":
            return self._fetch_tukas_records(symbol_upper)
        if symbol_upper == "TUCLK":
            return self._fetch_tuclk_records(symbol_upper)
        if symbol_upper == "MAKTK":
            return self._fetch_maktk_records(symbol_upper)
        if symbol_upper == "SAFKR":
            return self._fetch_safkr_records(symbol_upper)
        if symbol_upper == "SELVA":
            return self._fetch_selva_records(symbol_upper, config)
        if symbol_upper == "RUZYE":
            return self._fetch_ruzye_records(symbol_upper, config)
        if symbol_upper == "VANGD":
            return self._fetch_vangd_records(symbol_upper)
        if symbol_upper == "RNPOL":
            return self._fetch_rnpol_records(symbol_upper, config)
        if symbol_upper == "RODRG":
            return self._fetch_rodrg_records(symbol_upper)
        if symbol_upper == "GEDZA":
            return self._fetch_gedza_records(symbol_upper)
        if symbol_upper == "GUBRF":
            return self._fetch_gubrf_records(symbol_upper)
        if symbol_upper == "GIPTA":
            return self._fetch_gipta_records(symbol_upper)
        if symbol_upper == "GUNDG":
            return self._fetch_gundg_records(symbol_upper)
        if symbol_upper == "SNICA":
            return self._fetch_snica_records(symbol_upper)
        if symbol_upper == "IZINV":
            return self._fetch_izinv_records(symbol_upper)
        if symbol_upper == "TATGD":
            return self._fetch_tatgd_records(symbol_upper)
        if symbol_upper == "DOFER":
            return self._fetch_dofer_records(symbol_upper)
        if symbol_upper == "AGROT":
            return self._fetch_agrot_records(symbol_upper)
        if symbol_upper == "ALKA":
            return self._fetch_alka_records(symbol_upper)
        if symbol_upper == "EKOS":
            return self._fetch_ekos_records(symbol_upper)
        if symbol_upper == "MEGMT":
            return self._fetch_megmt_records(symbol_upper)
        if symbol_upper == "MEKAG":
            return self._fetch_mekag_records(symbol_upper)
        if symbol_upper == "KBORU":
            return self._fetch_kboru_records(symbol_upper)
        if symbol_upper == "PETUN":
            return self._fetch_petun_records(symbol_upper)
        if symbol_upper == "FMIZP":
            return self._fetch_fmizp_records(symbol_upper)
        if symbol_upper == "BRKSN":
            return self._fetch_brksn_records(symbol_upper)
        if symbol_upper == "DMRGD":
            return self._fetch_dmrgd_records(symbol_upper)
        if symbol_upper == "OFSYM":
            return self._fetch_ofsym_records(symbol_upper)
        if symbol_upper == "KONKA":
            return self._fetch_konka_records(symbol_upper)
        if symbol_upper == "KLSER":
            return self._fetch_klser_records(symbol_upper)
        if symbol_upper == "HATSN":
            return self._fetch_hatsn_records(symbol_upper)
        if symbol_upper == "EUPWR":
            return self._fetch_eupwr_records(symbol_upper)
        if symbol_upper == "MAKIM":
            return self._fetch_makim_records(symbol_upper)
        if symbol_upper == "TARKM":
            return self._fetch_tarkm_records(symbol_upper)
        if symbol_upper == "SEYKM":
            return self._fetch_seykm_records(symbol_upper)
        if symbol_upper == "SILVR":
            return self._fetch_silvr_records(symbol_upper)
        if symbol_upper == "ONCSM":
            return self._fetch_oncsm_records(symbol_upper)
        if symbol_upper == "KTSKR":
            return self._fetch_ktskr_records(symbol_upper, config)
        if symbol_upper == "ISKPL":
            return self._fetch_iskpl_records(symbol_upper)
        if symbol_upper == "ELITE":
            return self._fetch_elite_records(symbol_upper)
        if symbol_upper == "ERCB":
            return self._fetch_ercb_records(symbol_upper)
        if symbol_upper == "ISSEN":
            return self._fetch_issen_records(symbol_upper)
        if symbol_upper == "BIENY":
            return self._fetch_bieny_records(symbol_upper)
        if symbol_upper == "RUBNS":
            return self._fetch_rubns_records(symbol_upper)
        if symbol_upper == "KLSYN":
            return self._fetch_klsyn_records(symbol_upper)
        if symbol_upper == "ASTOR":
            return self._fetch_astor_records(symbol_upper)
        if symbol_upper == "SOKE":
            return self._fetch_soke_records(symbol_upper)
        if symbol_upper == "ORCAY":
            return self._fetch_orcay_records(symbol_upper)
        if symbol_upper == "BARMA":
            return self._fetch_barma_records(symbol_upper)
        if symbol_upper == "BAYRK":
            return self._fetch_bayrk_records(symbol_upper)
        if symbol_upper == "ANGEN":
            return self._fetch_angen_records(symbol_upper)
        if symbol_upper == "BMSTL":
            return self._fetch_bmstl_records(symbol_upper)
        if symbol_upper == "YYLGD":
            return self._fetch_yylgd_records(symbol_upper)
        if symbol_upper == "PNLSN":
            return self._fetch_pnlsn_records(symbol_upper)
        if symbol_upper == "FADE":
            return self._fetch_fade_records(symbol_upper)
        if symbol_upper == "TMPOL":
            return self._fetch_tmpol_records(symbol_upper)
        if symbol_upper == "NIBAS":
            return self._fetch_nibas_records(symbol_upper)
        if symbol_upper == "DURDO":
            return self._fetch_durdo_records(symbol_upper, config)
        if symbol_upper == "KAYSE":
            html = self._request_text(config.page_url, verify_ssl=config.verify_ssl)
            return self._parse_kayse_html(symbol_upper, html, config.page_url)
        if "financialreports.eu" in config.page_url:
            return self._fetch_financialreports_records(symbol_upper, config)
        pages = self._page_urls_for_config(config)
        records: list[dict] = []
        for page_url in pages:
            html = self._request_text(page_url, verify_ssl=config.verify_ssl)
            records.extend(self.parse_html(symbol_upper, html, page_url, verify_ssl=config.verify_ssl))
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_gedza_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6737574/": date(2023, 3, 1),
            "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6717121/": date(2023, 6, 1),
            "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701568/": date(2023, 9, 1),
            "https://financialreports.eu/filings/6661866/content/": date(2023, 12, 1),
            "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6648134/": date(2024, 3, 1),
            "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6625263/": date(2024, 6, 1),
            "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6614473/": date(2024, 9, 1),
            "https://financialreports.eu/filings/gediz-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2026/32909469/": date(2026, 3, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            if announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_alka_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 2),
                "announcement_source_url": "https://financialreports.eu/filings/alkim-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2026/32864135/",
            }
        ]

    def _fetch_hktm_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/hidropar-hareket-kontrol-teknolojileri-merkezi-sanayi-ve-ticaret-as/audit-report-information/2024/6661795/": date(2023, 12, 1),
            "https://financialreports.eu/filings/hidropar-hareket-kontrol-teknolojileri-merkezi-sanayi-ve-ticaret-as/annual-report/2024/6648941/": date(2024, 3, 1),
            "https://financialreports.eu/filings/6624330/content/": date(2024, 6, 1),
            "https://financialreports.eu/filings/6614020/content/": date(2024, 9, 1),
            "https://financialreports.eu/filings/hidropar-hareket-kontrol-teknolojileri-merkezi-sanayi-ve-ticaret-as/regulatory-filings/2026/43132006/": date(2026, 3, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_imasm_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2023/6719392/": date(2023, 6, 1),
            "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2023/6703629/": date(2023, 9, 1),
            "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2024/6675716/": date(2023, 12, 1),
            "https://financialreports.eu/filings/imas-makina-sanayi-as/interim-quarterly-report/2024/6648226/": date(2024, 3, 1),
            "https://financialreports.eu/filings/imas-makina-sanayi-as/report-publication-announcement/2024/6626690/": date(2024, 6, 1),
            "https://financialreports.eu/filings/imas-makina-sanayi-as/report-publication-announcement/2024/6615634/": date(2024, 9, 1),
            "https://financialreports.eu/filings/imas-makina-sanayi-as/report-publication-announcement/2026/32932268/": date(2026, 3, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_acsel_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6721056/": date(2023, 6, 1),
            "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6706227/": date(2023, 9, 1),
            "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6667790/": date(2023, 12, 1),
            "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6651272/": date(2024, 3, 1),
            "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6633749/": date(2024, 6, 1),
            "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6618190/": date(2024, 9, 1),
            "https://financialreports.eu/filings/aciselsan-acipayam-seluloz-sanayi-ve-ticaret-as/annual-report/2026/32866652/": date(2026, 3, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_blume_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2023/6717872/": date(2023, 6, 1),
            "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2023/6703000/": date(2023, 9, 1),
            "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/annual-report/2024/6677283/": date(2023, 12, 1),
            "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2024/6653686/": date(2024, 3, 1),
            "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2024/6629336/": date(2024, 6, 1),
            "https://financialreports.eu/filings/metemtur-yatirim-enerji-turizm-ve-insaat-as/interim-quarterly-report/2024/6615163/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_burce_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2023/6715537/": date(2023, 6, 1),
            "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2023/6700882/": date(2023, 9, 1),
            "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/annual-report/2024/6666115/": date(2023, 12, 1),
            "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2024/6648097/": date(2024, 3, 1),
            "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2024/6623389/": date(2024, 6, 1),
            "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/interim-quarterly-report/2024/6614442/": date(2024, 9, 1),
            "https://financialreports.eu/filings/burcelik-bursa-celik-dokum-sanayii-as/regulatory-filings/2026/36131474/": date(2026, 3, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_eggub_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 23),
                "announcement_source_url": "https://financialreports.eu/filings/ege-gubre-sanayii-as/regulatory-filings/2026/35683644/",
            },
        ]

    def _fetch_egser_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 22),
                "announcement_source_url": "https://financialreports.eu/filings/ege-seramik-sanayi-ve-ticaret-as/regulatory-filings/2026/35271483/",
            },
        ]

    def _fetch_durdo_records(self, symbol: str, config: IssuerIRSourceConfig) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2023/6736358/": date(2023, 3, 1),
            "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2023/6715801/": date(2023, 6, 1),
            "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2023/6700937/": date(2023, 9, 1),
            "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2024/6660090/": date(2023, 12, 1),
            "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2024/6647738/": date(2024, 3, 1),
            "https://financialreports.eu/filings/duran-dogan-basim-ve-ambalaj-sanayi-as/report-publication-announcement/2024/6623625/": date(2024, 6, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )

        candidate_urls = {
            date(2024, 9, 1): [
                "https://www.durukan.com.tr/wp-content/uploads/2024/10/DURUKAN_Faaliyet-Raporu_2024_3.pdf",
            ],
            date(2026, 3, 1): [
                "https://www.durukan.com.tr/wp-content/uploads/2026/05/2026-Yili-1.-Ceyrek-Faaliyet-Raporu.pdf",
            ],
        }
        for period_end, urls in candidate_urls.items():
            for url in urls:
                try:
                    announcement_date = self._resolve_publication_date(url, verify_ssl=config.verify_ssl)
                except Exception:
                    continue
                if announcement_date is None:
                    continue
                if not _publication_date_within_lag(period_end, announcement_date, config.max_publication_lag_days):
                    continue
                records.append(
                    {
                        "symbol": symbol.upper(),
                        "period_end": period_end,
                        "announcement_date": announcement_date,
                        "announcement_source_url": url,
                    }
                )
                break
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_silvr_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2023/6739916/": date(2023, 3, 1),
            "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2023/6719250/": date(2023, 6, 1),
            "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2023/6704073/": date(2023, 9, 1),
            "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2024/6659114/": date(2023, 12, 1),
            "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2024/6651309/": date(2024, 3, 1),
            "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2024/6626891/": date(2024, 6, 1),
            "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2024/6617683/": date(2024, 9, 1),
            "https://financialreports.eu/filings/silverline-endustri-ve-ticaret-as/report-publication-announcement/2026/38661174/": date(2026, 3, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            if announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_oncsm_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2023/6737520/": date(2023, 3, 1),
            "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2023/6721493/": date(2023, 6, 1),
            "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2023/6702769/": date(2023, 9, 1),
            "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2024/6672125/": date(2023, 12, 1),
            "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2024/6648272/": date(2024, 3, 1),
            "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2024/6623861/": date(2024, 6, 1),
            "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615160/": date(2024, 9, 1),
            "https://financialreports.eu/filings/oncosem-onkolojik-sistemler-sanayi-ve-ticaret-as/report-publication-announcement/2026/38661174/": date(2026, 3, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            if announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_ktskr_records(self, symbol: str, config: IssuerIRSourceConfig) -> list[dict]:
        candidate_urls = {
            date(2023, 3, 1): [
                "https://kutahyaseker.com.tr/data/1_a.pdf",
            ],
            date(2023, 6, 1): [
                "https://kutahyaseker.com.tr/data/faaliyet.pdf",
            ],
            date(2023, 9, 1): [
                "https://kutahyaseker.com.tr/data/2023_faliyet9.pdf",
            ],
            date(2023, 12, 1): [
                "https://kutahyaseker.com.tr/data/2023_faliyet12.pdf",
            ],
            date(2024, 3, 1): [
                "https://kutahyaseker.com.tr/data/2024_3_1.pdf",
            ],
            date(2024, 6, 1): [
                "https://kutahyaseker.com.tr/data/2024_3_2.pdf",
            ],
            date(2024, 9, 1): [
                "https://kutahyaseker.com.tr/data/2024_3_3.pdf",
            ],
            date(2026, 3, 1): [
                "https://kutahyaseker.com.tr/data/2026_1_1_1.pdf",
            ],
        }
        records: list[dict] = []
        for period_end, urls in candidate_urls.items():
            for url in urls:
                try:
                    announcement_date = self._resolve_publication_date(url, verify_ssl=config.verify_ssl)
                except Exception:
                    continue
                if announcement_date is None:
                    continue
                if not _publication_date_within_lag(period_end, announcement_date, config.max_publication_lag_days):
                    continue
                records.append(
                    {
                        "symbol": symbol.upper(),
                        "period_end": period_end,
                        "announcement_date": announcement_date,
                        "announcement_source_url": url,
                    }
                )
                break
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_iskpl_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6834416/": date(2021, 12, 1),
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6821644/": date(2022, 3, 1),
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6793791/": date(2022, 6, 1),
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2022/6781606/": date(2022, 9, 1),
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2023/6736439/": date(2023, 3, 1),
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2023/6716775/": date(2023, 6, 1),
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2023/6701034/": date(2023, 9, 1),
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6661315/": date(2023, 12, 1),
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6648279/": date(2024, 3, 1),
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6624743/": date(2024, 6, 1),
            "https://financialreports.eu/filings/isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as/report-publication-announcement/2024/6614373/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        records.append(
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 11),
                "announcement_source_url": "https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/iskpl-isik-plastik-sanayi-ve-dis-ticaret-pazarlama-as-finansal-rapor_ID3493402/",
            }
        )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_fade_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2023/6736782/": date(2023, 3, 1),
            "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2023/6715340/": date(2023, 6, 1),
            "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2023/6701456/": date(2023, 9, 1),
            "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2024/6680523/": date(2023, 12, 1),
            "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2024/6648859/": date(2024, 3, 1),
            "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2024/6623863/": date(2024, 6, 1),
            "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/report-publication-announcement/2024/6615199/": date(2024, 9, 1),
            "https://financialreports.eu/filings/fade-gida-yatirim-sanayi-ticaret-as/regulatory-filings/2026/44302130/": date(2026, 3, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_elite_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6714990/": date(2023, 6, 1),
            "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6700888/": date(2023, 9, 1),
            "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6660156/": date(2023, 12, 1),
            "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6647222/": date(2024, 3, 1),
            "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6622299/": date(2024, 6, 1),
            "https://financialreports.eu/filings/elite-naturel-organik-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6614944/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_ercb_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2023/6716447/": date(2023, 6, 1),
            "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2023/6701257/": date(2023, 9, 1),
            "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2024/6679201/": date(2023, 12, 1),
            "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2024/6663363/": date(2024, 3, 1),
            "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2024/6633823/": date(2024, 6, 1),
            "https://financialreports.eu/filings/erciyas-celik-boru-sanayi-as/report-publication-announcement/2024/6614367/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_issen_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2023/6717044/": date(2023, 6, 1),
            "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2023/6702021/": date(2023, 9, 1),
            "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2024/6675368/": date(2023, 12, 1),
            "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2024/6650313/": date(2024, 3, 1),
            "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2024/6628633/": date(2024, 6, 1),
            "https://financialreports.eu/filings/isbir-sentetik-dokuma-sanayi-as/report-publication-announcement/2024/6614115/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_pnlsn_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6721796/": date(2023, 6, 1),
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704832/": date(2023, 9, 1),
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6673821/": date(2023, 12, 1),
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6650834/": date(2024, 3, 1),
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6626542/": date(2024, 6, 1),
            "https://financialreports.eu/filings/panelsan-cati-cephe-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6617578/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_bieny_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2023/6728459/": date(2023, 3, 1),
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2023/6715000/": date(2023, 6, 1),
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2023/6700939/": date(2023, 9, 1),
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6660739/": date(2023, 12, 1),
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6647696/": date(2024, 3, 1),
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6623222/": date(2024, 6, 1),
            "https://financialreports.eu/filings/bien-yapi-urunleri-sanayi-turizm-ve-ticaret-as/report-publication-announcement/2024/6614285/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_rubns_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2023/6719612/": date(2023, 6, 1),
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2023/6703889/": date(2023, 9, 1),
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6670855/": date(2023, 12, 1),
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6655697/": date(2024, 3, 1),
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6626593/": date(2024, 6, 1),
            "https://financialreports.eu/filings/rubenis-tekstil-sanayi-ticaret-as/report-publication-announcement/2024/6617753/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_klsyn_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2023/6736316/": date(2023, 3, 1),
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2023/6715640/": date(2023, 6, 1),
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2023/6702127/": date(2023, 9, 1),
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2024/6659919/": date(2023, 12, 1),
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2024/6650259/": date(2024, 3, 1),
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/interim-quarterly-report/2024/6624322/": date(2024, 6, 1),
            "https://financialreports.eu/filings/koleksiyon-mobilya-sanayi-as/report-publication-announcement/2024/6616108/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_astor_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2023/6719327/": date(2023, 6, 1),
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2023/6703549/": date(2023, 9, 1),
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6682368/": date(2023, 12, 1),
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6657125/": date(2024, 3, 1),
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6632006/": date(2024, 6, 1),
            "https://financialreports.eu/filings/astor-enerji-as/report-publication-announcement/2024/6617944/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_soke_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6716316/": date(2023, 6, 1),
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701739/": date(2023, 9, 1),
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6660945/": date(2023, 12, 1),
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6649362/": date(2024, 3, 1),
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6624161/": date(2024, 6, 1),
            "https://financialreports.eu/filings/soke-degirmencilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615337/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_orcay_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2023/6738122/": date(2023, 3, 1),
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2023/6718383/": date(2023, 6, 1),
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701516/": date(2023, 9, 1),
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6668629/": date(2023, 12, 1),
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6651974/": date(2024, 3, 1),
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6631022/": date(2024, 6, 1),
            "https://financialreports.eu/filings/orcay-ortakoy-cay-sanayi-ve-ticaret-as/report-publication-announcement/2024/6618585/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_barma_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6740089/": date(2023, 3, 1),
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6719904/": date(2023, 6, 1),
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2023/6705060/": date(2023, 9, 1),
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6757948/": date(2023, 12, 1),
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6651443/": date(2024, 3, 1),
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6625397/": date(2024, 6, 1),
            "https://financialreports.eu/filings/barem-ambalaj-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615554/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_bayrk_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2023/6733814/": date(2023, 3, 1),
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6720153/": date(2023, 6, 1),
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/report-publication-announcement/2023/6706360/": date(2023, 9, 1),
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/audit-report-information/2024/6671514/": date(2023, 12, 1),
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650996/": date(2024, 3, 1),
            "https://financialreports.eu/filings/6627967/content/": date(2024, 6, 1),
            "https://financialreports.eu/filings/bayrak-ebt-taban-sanayi-ve-ticaret-as/report-publication-announcement/2024/6611393/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_angen_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/anatolia-tani-ve-biyoteknoloji-urunleri-arastirma-gelistirme-sanayi-ve-ticaret-as/environmental-social-information/2023/6717458/": date(2023, 6, 1),
            "https://financialreports.eu/filings/anatolia-tani-ve-biyoteknoloji-urunleri-arastirma-gelistirme-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6702846/": date(2023, 9, 1),
            "https://financialreports.eu/filings/6663320/content/": date(2023, 12, 1),
            "https://financialreports.eu/filings/6649346/content/": date(2024, 3, 1),
            "https://financialreports.eu/filings/6625212/content/": date(2024, 6, 1),
            "https://financialreports.eu/filings/anatolia-tani-ve-biyoteknoloji-urunleri-arastirma-gelistirme-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6615182/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_bmstl_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6720248/": date(2023, 6, 1),
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6698120/": date(2023, 9, 1),
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/report-publication-announcement/2024/6674891/": date(2023, 12, 1),
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6655248/": date(2024, 3, 1),
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6624971/": date(2024, 6, 1),
            "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/earnings-release/2024/6615416/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_bmsch_records(self, symbol: str) -> list[dict]:
        # BMSTL's official site mislabels several 2022 archive entries. For the
        # post-listing gap window, the FinancialReports regulator archive gives
        # cleaner release dates for the actual Q1/Q2/Q3 2022 filings.
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2022, 3, 1),
                "announcement_date": date(2022, 5, 16),
                "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2022/6808211/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2022, 6, 1),
                "announcement_date": date(2022, 8, 8),
                "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2022/6795474/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2022, 9, 1),
                "announcement_date": date(2022, 10, 28),
                "announcement_source_url": "https://financialreports.eu/filings/bms-birlesik-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2022/6783017/",
            },
        ]

    def _fetch_yylgd_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6734516/": date(2023, 3, 1),
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6719711/": date(2023, 6, 1),
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6705747/": date(2023, 9, 1),
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6666007/": date(2023, 12, 1),
            "https://financialreports.eu/filings/6662132/content/": date(2024, 3, 1),
            "https://financialreports.eu/filings/6627740/content/": date(2024, 6, 1),
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2024/6621683/": date(2024, 9, 1),
            "https://financialreports.eu/filings/yayla-agro-gida-sanayi-ve-ticaret-as/report-publication-announcement/2026/8243505/": date(2026, 3, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_rodrg_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2023/6737731/": date(2023, 3, 1),
            "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2023/6717589/": date(2023, 6, 1),
            "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2023/6702901/": date(2023, 9, 1),
            "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2024/6686105/": date(2023, 12, 1),
            "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2024/6654426/": date(2024, 3, 1),
            "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/regulatory-filings/2024/6636473/": date(2024, 6, 1),
            "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2024/6614951/": date(2024, 9, 1),
            "https://financialreports.eu/filings/rodrigo-tekstil-sanayi-ve-ticaret-as/report-publication-announcement/2026/32918984/": date(2026, 3, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_rnpol_records(self, symbol: str, config: IssuerIRSourceConfig) -> list[dict]:
        records: list[dict] = []
        for page_url in self._page_urls_for_config(config):
            html = self._request_text(page_url, verify_ssl=config.verify_ssl)
            records.extend(self.parse_html(symbol, html, page_url, verify_ssl=config.verify_ssl))

        financialreports_config = IssuerIRSourceConfig(
            symbol=symbol,
            page_url="https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/annual-quarterly-financial-statement/2022/6810965/",
            extra_page_urls=(
                "https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/interim-quarterly-report/2022/6790300/",
                "https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/annual-quarterly-financial-statement/2022/6782047/",
                "https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/annual-quarterly-financial-statement/2024/6673138/",
            ),
        )
        records.extend(self._fetch_financialreports_records(symbol, financialreports_config))

        manual_financialreports_periods = {
            "https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/report-publication-announcement/2023/6755806/": date(2022, 12, 1),
            "https://financialreports.eu/filings/rainbow-polikarbonat-sanayi-ticaret-as/annual-quarterly-financial-statement/2024/6673766/": date(2023, 12, 1),
        }
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_ruzye_records(self, symbol: str, config: IssuerIRSourceConfig) -> list[dict]:
        records: list[dict] = []
        for page_url in self._page_urls_for_config(config):
            html = self._request_text(page_url, verify_ssl=config.verify_ssl)
            records.extend(self.parse_html(symbol, html, page_url, verify_ssl=config.verify_ssl))

        manual_financialreports_periods = {
            "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6733981/": date(2023, 3, 1),
            "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6718283/": date(2023, 6, 1),
            "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6703215/": date(2023, 9, 1),
            "https://financialreports.eu/filings/6660224/content/": date(2023, 12, 1),
            "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6647891/": date(2024, 3, 1),
            "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6624946/": date(2024, 6, 1),
            "https://financialreports.eu/filings/ruzy-madencilik-ve-enerji-yatirimlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6616196/": date(2024, 9, 1),
        }
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_burva_records(self, symbol: str) -> list[dict]:
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/burcelik-vana-sanayi-ve-ticaret-as/report-publication-announcement/2023/6718973/": date(2023, 6, 1),
            "https://financialreports.eu/filings/burcelik-vana-sanayi-ve-ticaret-as/audit-report-information/2023/6704106/": date(2023, 9, 1),
            "https://financialreports.eu/filings/6665973/content/": date(2023, 12, 1),
            "https://financialreports.eu/filings/6650915/content/": date(2024, 3, 1),
            "https://financialreports.eu/filings/6627811/content/": date(2024, 6, 1),
            "https://financialreports.eu/filings/burcelik-vana-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6618004/": date(2024, 9, 1),
        }
        records: list[dict] = []
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None or announcement_date < period_end:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_kopol_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://financialreports.eu/filings/koza-polyester-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6718876/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/koza-polyester-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704320/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 2, 29),
                "announcement_source_url": "https://financialreports.eu/filings/koza-polyester-sanayi-ve-ticaret-as/audit-report-information/2024/6678474/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 4, 30),
                "announcement_source_url": "https://financialreports.eu/filings/6667515/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 8, 8),
                "announcement_source_url": "https://financialreports.eu/filings/6636072/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/6617840/content/",
            },
        ]

    def _fetch_dardl_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 5, 10),
                "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/annual-quarterly-financial-statement/2023/6736161/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 21),
                "announcement_source_url": "https://financialreports.eu/filings/6715291/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/report-publication-announcement/2023/6700737/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 5, 22),
                "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/interim-quarterly-report/2024/6658344/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 10, 4),
                "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/interim-quarterly-report/2024/6621827/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/report-publication-announcement/2024/6614140/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 11),
                "announcement_source_url": "https://financialreports.eu/filings/dardanel-onentas-gida-sanayi-as/interim-quarterly-report/2026/32931685/",
            },
        ]

    def _fetch_dokta_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 9),
                "announcement_source_url": "https://financialreports.eu/filings/doktas-dokumculuk-ticaret-ve-sanayi-as/interim-quarterly-report/2026/32919101/",
            },
        ]

    def _fetch_bntas_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 4, 29),
                "announcement_source_url": "https://www.bantas.com.tr/wp-content/uploads/2023/04/FaaliyetRaporu.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 29),
                "announcement_source_url": "https://financialreports.eu/filings/bantas-bandirma-ambalaj-sanayi-ticaret-as/report-publication-announcement/2026/38656829/",
            },
        ]

    def _fetch_dagi_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 5, 10),
                "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2023/6736234/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 18),
                "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2023/6715321/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701209/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 26),
                "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2024/6668750/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 7),
                "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2024/6652092/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 8, 23),
                "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2024/6632483/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615320/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 11),
                "announcement_source_url": "https://financialreports.eu/filings/dagi-giyim-sanayi-ve-ticaret-as/report-publication-announcement/2026/32930519/",
            },
        ]

    def _fetch_dgnmo_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 11),
                "announcement_source_url": "https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/dgnmo-doganlar-mobilya-grubu-imalat-sanayi-ve-ticaret-as-finansal-rapor_ID3493937/",
            }
        ]

    def _fetch_gubrf_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 19),
                "announcement_source_url": "https://www.gubretas.com.tr/uploads/files/pages/gubretas-rapor-spk-30.06.2023-287.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 8),
                "announcement_source_url": "https://www.gubretas.com.tr/uploads/files/pages/gubretas-rapor-spk-31.12.2023-842.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 20),
                "announcement_source_url": "https://www.gubretas.com.tr/uploads/files/pages/31-mart-2024-finansal-tablo-ve-dipnotlar-899.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 25),
                "announcement_source_url": "https://www.gubretas.com.tr/uploads/files/pages/30-haziran-2024-finansal-tablo-ve-dipnotlar-928.pdf",
            },
        ]

    def _fetch_gipta_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 27),
                "announcement_source_url": "https://financialreports.eu/filings/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/interim-quarterly-report/2023/6705005/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 3),
                "announcement_source_url": "https://financialreports.eu/filings/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/interim-quarterly-report/2024/6666776/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/interim-quarterly-report/2024/6650972/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 8, 19),
                "announcement_source_url": "https://financialreports.eu/filings/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/interim-quarterly-report/2024/6633672/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/gipta-ofis-kirtasiye-ve-promosyon-urunleri-imalat-sanayi-as/interim-quarterly-report/2024/6617617/",
            },
        ]

    def _fetch_tatgd_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2019, 3, 1),
                "announcement_date": date(2019, 4, 27),
                "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2019/6992412/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2019, 6, 1),
                "announcement_date": date(2019, 8, 7),
                "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2019/6978065/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2019, 9, 1),
                "announcement_date": date(2019, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2019/6968857/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2019, 12, 1),
                "announcement_date": date(2020, 2, 12),
                "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2020/6956910/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2020, 3, 1),
                "announcement_date": date(2020, 5, 14),
                "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2020/6940168/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2020, 6, 1),
                "announcement_date": date(2020, 8, 6),
                "announcement_source_url": "https://financialreports.eu/filings/tat-gida-sanayi-as/interim-quarterly-report/2020/6927225/",
            },
        ]

    def _fetch_dofer_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 6),
                "announcement_source_url": "https://financialreports.eu/filings/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6665721/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650533/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 18),
                "announcement_source_url": "https://financialreports.eu/filings/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6626754/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 28),
                "announcement_source_url": "https://financialreports.eu/filings/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6618352/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 29),
                "announcement_source_url": "https://financialreports.eu/filings/dofer-yapi-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2026/38655889/",
            },
        ]

    def _fetch_agrot_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 16),
                "announcement_source_url": "https://financialreports.eu/filings/agrotech-yuksek-teknoloji-ve-yatirim-as/interim-quarterly-report/2024/6671612/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 4, 17),
                "announcement_source_url": "https://financialreports.eu/filings/agrotech-yuksek-teknoloji-ve-yatirim-as/interim-quarterly-report/2024/6670897/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 27),
                "announcement_source_url": "https://financialreports.eu/filings/agrotech-yuksek-teknoloji-ve-yatirim-as/interim-quarterly-report/2024/6624190/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/agrotech-yuksek-teknoloji-ve-yatirim-as/interim-quarterly-report/2024/6614217/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 11),
                "announcement_source_url": "https://financialreports.eu/filings/agrotech-yuksek-teknoloji-ve-yatirim-as/interim-quarterly-report/2026/32932166/",
            },
        ]

    def _fetch_ekos_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 10),
                "announcement_source_url": "https://financialreports.eu/filings/ekos-teknoloji-ve-elektrik-as/interim-quarterly-report/2024/6663344/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 21),
                "announcement_source_url": "https://financialreports.eu/filings/ekos-teknoloji-ve-elektrik-as/interim-quarterly-report/2024/6647209/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 27),
                "announcement_source_url": "https://financialreports.eu/filings/ekos-teknoloji-ve-elektrik-as/interim-quarterly-report/2024/6624054/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/ekos-teknoloji-ve-elektrik-as/interim-quarterly-report/2024/6614987/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 11),
                "announcement_source_url": "https://financialreports.eu/filings/ekos-teknoloji-ve-elektrik-as/interim-quarterly-report/2026/32930742/",
            },
        ]

    def _fetch_megmt_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 2, 23),
                "announcement_source_url": "https://financialreports.eu/filings/mega-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6683050/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 4, 30),
                "announcement_source_url": "https://financialreports.eu/filings/mega-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6667236/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 8, 14),
                "announcement_source_url": "https://financialreports.eu/filings/mega-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6634706/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 4),
                "announcement_source_url": "https://financialreports.eu/filings/mega-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6616787/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 5),
                "announcement_source_url": "https://financialreports.eu/filings/mega-metal-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32904875/",
            },
        ]

    def _fetch_mekag_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 25),
                "announcement_source_url": "https://financialreports.eu/filings/meka-global-makine-imalat-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6669069/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 14),
                "announcement_source_url": "https://financialreports.eu/filings/meka-global-makine-imalat-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6649105/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 26),
                "announcement_source_url": "https://financialreports.eu/filings/meka-global-makine-imalat-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6624301/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 22),
                "announcement_source_url": "https://financialreports.eu/filings/meka-global-makine-imalat-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6611862/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 6),
                "announcement_source_url": "https://financialreports.eu/filings/meka-global-makine-imalat-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32909378/",
            },
        ]

    def _fetch_kboru_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 2, 29),
                "announcement_source_url": "https://financialreports.eu/filings/kuzey-boru-as/interim-quarterly-report/2024/6681327/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 7),
                "announcement_source_url": "https://financialreports.eu/filings/kuzey-boru-as/interim-quarterly-report/2024/6652487/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 11),
                "announcement_source_url": "https://financialreports.eu/filings/kuzey-boru-as/interim-quarterly-report/2024/6628696/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/kuzey-boru-as/interim-quarterly-report/2024/6618010/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 30),
                "announcement_source_url": "https://www.vkyanaliz.com/rap/KBORU_2026-05-04_39856.pdf",
            },
        ]

    def _fetch_petun_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 30),
                "announcement_source_url": "https://www.vkyanaliz.com/rap/PETUN_2026-05-05_40256.pdf",
            },
        ]

    def _fetch_fmizp_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 27),
                "announcement_source_url": "https://www.vkyanaliz.com/rap/FMIZP_2026-05-04_39574.pdf",
            },
        ]

    def _fetch_izinv_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 2),
                "announcement_source_url": "https://financialreports.eu/filings/iz-yatirim-holding-as/report-publication-announcement/2023/6721312/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/iz-yatirim-holding-as/report-publication-announcement/2023/6704175/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 16),
                "announcement_source_url": "https://financialreports.eu/filings/iz-yatirim-holding-as/report-publication-announcement/2024/6661309/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2025, 3, 1),
                "announcement_date": date(2025, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/iz-yatirim-holding-as/report-publication-announcement/2025/6556852/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 12),
                "announcement_source_url": "https://financialreports.eu/filings/iz-yatirim-holding-as/report-publication-announcement/2026/45333805/",
            },
        ]

    def _fetch_gundg_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/gundogdu-gida-sut-urunleri-sanayi-ve-dis-ticaret-as/report-publication-announcement/2024/6617920/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 12, 1),
                "announcement_date": date(2025, 3, 13),
                "announcement_source_url": "https://financialreports.eu/filings/gundogdu-gida-sut-urunleri-sanayi-ve-dis-ticaret-as/report-publication-announcement/2025/6584826/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2025, 3, 1),
                "announcement_date": date(2025, 4, 30),
                "announcement_source_url": "https://financialreports.eu/filings/gundogdu-gida-sut-urunleri-sanayi-ve-dis-ticaret-as/report-publication-announcement/2025/6569025/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2025, 6, 1),
                "announcement_date": date(2025, 8, 11),
                "announcement_source_url": "https://financialreports.eu/filings/gundogdu-gida-sut-urunleri-sanayi-ve-dis-ticaret-as/report-publication-announcement/2025/7709601/",
            },
        ]

    def _fetch_snica_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2023/6718096/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2023/6704663/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 15),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2024/6671987/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 2),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2026/32865891/",
            },
        ]

    def _fetch_tmpol_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 5, 10),
                "announcement_source_url": "https://www.temapol.com.tr/images//ContentFiles/Temapol%2031.03.2023%20Konsolide.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://www.temapol.com.tr/images//ContentFiles/Temapol%2030.09.2023%20Konsolide%20SPK%209.11.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 21),
                "announcement_source_url": "https://www.temapol.com.tr/images//ContentFiles/Temapol%20Konsolide%2031.03.2024.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 30),
                "announcement_source_url": "https://www.temapol.com.tr/images//ContentFiles/Temapol%2030%20Haziran%202024%20Ba%C4%9F%C4%B1ms%C4%B1z%20Denetim%20Raporu.pdf",
            },
        ]

    def _fetch_nibas_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 4, 28),
                "announcement_source_url": "https://www.nigbas.com.tr/cms/uploads/files/mali_tablo_1220.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 8),
                "announcement_source_url": "https://www.nigbas.com.tr/cms/uploads/files/mali_tablo_2647.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 26),
                "announcement_source_url": "https://www.nigbas.com.tr/cms/uploads/files/mali_tablo_2942.pdf",
            },
        ]

    def _fetch_brksn_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 5, 9),
                "announcement_source_url": "https://kap.org.tr/tr/Bildirim/1149276",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 6),
                "announcement_source_url": "https://finans.cnnturk.com/kap-haberi/brksn-berkosan-yalitim-ve-tecrit-maddeleri-uretim-ve-ticaret-as-faaliyet-raporu-konsolide--3047607",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 20),
                "announcement_source_url": "https://financialreports.eu/filings/berkosan-yalitim-ve-tecrit-maddeleri-uretim-ve-ticaret-as/interim-quarterly-report/2024/6648140/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 27),
                "announcement_source_url": "https://financialreports.eu/filings/berkosan-yalitim-ve-tecrit-maddeleri-uretim-ve-ticaret-as/interim-quarterly-report/2024/6624179/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 11),
                "announcement_source_url": "https://financialreports.eu/filings/berkosan-yalitim-ve-tecrit-maddeleri-uretim-ve-ticaret-as/management-reports/2026/32930579/",
            },
        ]

    def _fetch_dmrgd_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/interim-quarterly-report/2023/6704252/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 6),
                "announcement_source_url": "https://financialreports.eu/filings/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/interim-quarterly-report/2024/6666153/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 20),
                "announcement_source_url": "https://financialreports.eu/filings/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/interim-quarterly-report/2024/6648118/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 30),
                "announcement_source_url": "https://financialreports.eu/filings/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/interim-quarterly-report/2024/6623250/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as/interim-quarterly-report/2024/6614069/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 11),
                "announcement_source_url": "https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/dmrgd-dmr-unlu-mamuller-uretim-gida-toptan-perakende-ihracat-as-finansal-rapor_ID3493521/",
            },
        ]

    def _fetch_ofsym_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/ofis-yem-gida-sanayi-ticaret-as/interim-quarterly-report/2023/6704252/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 6),
                "announcement_source_url": "https://financialreports.eu/filings/ofis-yem-gida-sanayi-ticaret-as/interim-quarterly-report/2024/6666153/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 20),
                "announcement_source_url": "https://financialreports.eu/filings/ofis-yem-gida-sanayi-ticaret-as/interim-quarterly-report/2024/6648118/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 30),
                "announcement_source_url": "https://financialreports.eu/filings/ofis-yem-gida-sanayi-ticaret-as/interim-quarterly-report/2024/6623250/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/ofis-yem-gida-sanayi-ticaret-as/interim-quarterly-report/2024/6614069/",
            },
        ]

    def _fetch_konka_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6704045/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 9),
                "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6663765/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650902/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 20),
                "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6625716/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6618075/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 2),
                "announcement_source_url": "https://financialreports.eu/filings/konya-kagit-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32864435/",
            },
        ]

    def _fetch_klser_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 27),
                "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2023/6705030/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 2),
                "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2024/6667161/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 21),
                "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2024/6647796/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 30),
                "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2024/6623333/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2024/6614925/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 6),
                "announcement_source_url": "https://financialreports.eu/filings/kaleseramik-canakkale-kalebodur-seramik-sanayi-as/interim-quarterly-report/2026/32909481/",
            },
        ]

    def _fetch_hatsn_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 28),
                "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6704690/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 4),
                "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6666204/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 10),
                "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/report-publication-announcement/2024/6651796/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 7),
                "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/report-publication-announcement/2024/6629398/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 12),
                "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/report-publication-announcement/2024/6613674/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 29),
                "announcement_source_url": "https://financialreports.eu/filings/hat-san-gemi-insaa-bakim-onarim-deniz-nakliyat-sanayi-ve-ticaret-as/report-publication-announcement/2026/38668529/",
            },
        ]

    def _fetch_eupwr_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 5, 22),
                "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2023/6733625/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 18),
                "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2023/6715351/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2023/6701147/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 2),
                "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2024/6667131/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 5, 22),
                "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2024/6658586/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 13),
                "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2024/6628030/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/europower-enerji-ve-otomasyon-teknolojileri-sanayi-ticaret-as/interim-quarterly-report/2024/6614536/",
            },
        ]

    def _fetch_makim_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 9),
                "announcement_source_url": "https://financialreports.eu/filings/makim-makina-teknolojileri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6663915/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/makim-makina-teknolojileri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650843/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 18),
                "announcement_source_url": "https://financialreports.eu/filings/makim-makina-teknolojileri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6626599/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/makim-makina-teknolojileri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6617864/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 2),
                "announcement_source_url": "https://financialreports.eu/filings/makim-makina-teknolojileri-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32864162/",
            },
        ]

    def _fetch_tarkm_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2022, 12, 1),
                "announcement_date": date(2023, 3, 1),
                "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6758497/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6719272/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6704536/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 4),
                "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6673252/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650898/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 20),
                "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6625753/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6617672/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 2),
                "announcement_source_url": "https://financialreports.eu/filings/tarkim-bitki-koruma-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32866316/",
            },
        ]

    def _fetch_seykm_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 7),
                "announcement_source_url": "https://file.portay.com.tr/files/2023/08/Seyitler_06_2023_SPK_TR.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 26),
                "announcement_source_url": "https://file.portay.com.tr/files/2023/11/Seyitler_09_2023_SPK_TR.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 8),
                "announcement_source_url": "https://file.portay.com.tr/files/2024/05/Seyitler_12_2023_SPK_TR.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 10),
                "announcement_source_url": "https://file.portay.com.tr/files/2024/06/Seyitler_03_2024_SPK_TR.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 19),
                "announcement_source_url": "https://file.portay.com.tr/files/2024/10/Seyitler_06_2024_SPK_TR.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://file.portay.com.tr/files/2024/12/Seyitler_09_2024_SPK_TR.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 11),
                "announcement_source_url": "https://file.portay.com.tr/files/2026/Seyitler_03_2026_SPK_TR.pdf",
            },
        ]

    def _fetch_cusan_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 5, 10),
                "announcement_source_url": "https://financialreports.eu/filings/6735985/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 23),
                "announcement_source_url": "https://financialreports.eu/filings/cuhadaroglu-metal-sanayi-ve-pazarlama-as/interim-quarterly-report/2024/6632276/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/cuhadaroglu-metal-sanayi-ve-pazarlama-as/interim-quarterly-report/2023/6700928/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 3),
                "announcement_source_url": "https://financialreports.eu/filings/cuhadaroglu-metal-sanayi-ve-pazarlama-as/annual-report/2024/6666402/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 5, 21),
                "announcement_source_url": "https://financialreports.eu/filings/cuhadaroglu-metal-sanayi-ve-pazarlama-as/annual-quarterly-financial-statement/2024/6658835/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 8, 23),
                "announcement_source_url": "https://financialreports.eu/filings/cuhadaroglu-metal-sanayi-ve-pazarlama-as/interim-quarterly-report/2024/6632276/",
            },
        ]

    def _fetch_dnisi_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 3),
                "announcement_source_url": "https://financialreports.eu/filings/6721009/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 3),
                "announcement_source_url": "https://financialreports.eu/filings/dinamik-isi-makina-yalitim-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6704328/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 18),
                "announcement_source_url": "https://financialreports.eu/filings/dinamik-isi-makina-yalitim-malzemeleri-sanayi-ve-ticaret-as/annual-report/2024/6669492/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 13),
                "announcement_source_url": "https://financialreports.eu/filings/dinamik-isi-makina-yalitim-malzemeleri-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6650138/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 13),
                "announcement_source_url": "https://financialreports.eu/filings/dinamik-isi-makina-yalitim-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6627449/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/dinamik-isi-makina-yalitim-malzemeleri-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6615855/",
            },
        ]

    def _fetch_dogub_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 8),
                "announcement_source_url": "https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/business-and-financial-review/2023/6719811/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 27),
                "announcement_source_url": "https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704993/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 10),
                "announcement_source_url": "https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/report-publication-announcement/2024/6651887/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 4),
                "announcement_source_url": "https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6630246/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/dogusan-boru-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6617774/",
            },
        ]

    def _fetch_frigo_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701425/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 14),
                "announcement_source_url": "https://financialreports.eu/filings/frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6662043/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 7, 3),
                "announcement_source_url": "https://financialreports.eu/filings/frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6644020/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 27),
                "announcement_source_url": "https://financialreports.eu/filings/frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6624074/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6615156/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 12, 1),
                "announcement_date": date(2025, 3, 5),
                "announcement_source_url": "https://financialreports.eu/filings/6589714/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 11),
                "announcement_source_url": "https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/frigo-frigo-pak-gida-maddeleri-sanayi-ve-ticaret-as-finansal-rapor_ID3493576/",
            },
        ]

    def _fetch_desa_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 7),
                "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6720158/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6703864/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 3, 27),
                "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6675485/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 22),
                "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6647244/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 10),
                "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6629018/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 6),
                "announcement_source_url": "https://financialreports.eu/filings/desa-deri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6616241/",
            },
        ]

    def _fetch_przma_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 8),
                "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6719910/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 27),
                "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704815/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 24),
                "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6669605/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6650860/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 20),
                "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/report-publication-announcement/2024/6625610/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 30),
                "announcement_source_url": "https://financialreports.eu/filings/prizma-pres-matbaacilik-yayincilik-sanayi-ve-ticaret-as/regulatory-filings/2026/39126088/",
            },
        ]

    def _fetch_egpro_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 23),
                "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2023/6714471/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 7),
                "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2023/6702184/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 2, 28),
                "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2024/6682107/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 5, 16),
                "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/interim-quarterly-report/2024/6661042/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 8, 22),
                "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2024/6632517/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/6615564/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 12),
                "announcement_source_url": "https://financialreports.eu/filings/ege-profil-ticaret-ve-sanayi-as/report-publication-announcement/2026/45021431/",
            },
        ]

    def _fetch_formt_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 7, 7),
                "announcement_source_url": "https://financialreports.eu/filings/formet-metal-ve-cam-sanayi-as/report-publication-announcement/2023/6725953/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 19),
                "announcement_source_url": "https://financialreports.eu/filings/formet-metal-ve-cam-sanayi-as/report-publication-announcement/2024/6670357/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 22),
                "announcement_source_url": "https://financialreports.eu/filings/formet-metal-ve-cam-sanayi-as/interim-quarterly-report/2024/6647253/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 27),
                "announcement_source_url": "https://financialreports.eu/filings/6623959/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/6613919/content/",
            },
        ]

    def _fetch_jants_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 9, 5),
                "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6712574/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/report-publication-announcement/2023/6703648/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 3, 4),
                "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/annual-report/2024/6681105/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 5, 16),
                "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6661253/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 19),
                "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6626216/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 25),
                "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/report-publication-announcement/2024/6618784/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 16),
                "announcement_source_url": "https://financialreports.eu/filings/jantsa-jant-sanayi-ve-ticaret-as/regulatory-filings/2026/34646438/",
            },
        ]

    def _fetch_gerel_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 16),
                "announcement_source_url": "https://financialreports.eu/filings/6716635/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/gersan-elektrik-ticaret-ve-sanayi-as/interim-quarterly-report/2023/6700805/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 4),
                "announcement_source_url": "https://financialreports.eu/filings/6673235/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 5, 22),
                "announcement_source_url": "https://financialreports.eu/filings/6657725/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 30),
                "announcement_source_url": "https://financialreports.eu/filings/gersan-elektrik-ticaret-ve-sanayi-as/interim-quarterly-report/2024/6623378/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/6614786/content/",
            },
        ]

    def _fetch_kartn_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 16),
                "announcement_source_url": "https://financialreports.eu/filings/kartonsan-karton-sanayi-ve-ticaret-as/regulatory-filings/2023/6716657/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 6),
                "announcement_source_url": "https://financialreports.eu/filings/kartonsan-karton-sanayi-ve-ticaret-as/regulatory-filings/2023/6702570/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 6),
                "announcement_source_url": "https://financialreports.eu/filings/kartonsan-karton-sanayi-ve-ticaret-as/annual-report/2024/6665375/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 5, 22),
                "announcement_source_url": "https://financialreports.eu/filings/6657785/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 8, 23),
                "announcement_source_url": "https://financialreports.eu/filings/kartonsan-karton-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2024/6632412/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 8),
                "announcement_source_url": "https://cdn.financialreports.eu/financialreports/media/filings/8938/2024/RNS/8938_rns_2024-11-08_b4391c65-8558-4e1d-968f-2f3f9bc55c8d.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 11),
                "announcement_source_url": "https://bigpara.hurriyet.com.tr/haberler/kap-haberleri/kartn-kartonsan-karton-sanayi-ve-ticaret-as-finansal-rapor_ID3493423/",
            },
        ]

    def _fetch_luksk_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/6700873/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 25),
                "announcement_source_url": "https://financialreports.eu/filings/6669325/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 20),
                "announcement_source_url": "https://financialreports.eu/filings/6625816/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 14),
                "announcement_source_url": "https://financialreports.eu/filings/6613167/content/",
            },
        ]

    def _fetch_mercn_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 5, 9),
                "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6737252/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 16),
                "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6716837/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 7),
                "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6702058/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 20),
                "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6659692/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 21),
                "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6647806/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 13),
                "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6627724/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/mercan-kimya-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6614199/",
            },
        ]

    def _fetch_marbl_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 23),
                "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2023/11/TUREKS-KONSOL_DE-30.09.2023-DIPNOT.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 9),
                "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2024/04/TUREKS-A._.-31.12.2023-Ba__ms_z-Denetim-Raporu.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 12),
                "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2024/07/1298683.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 23),
                "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2024/09/1337024.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 9),
                "announcement_source_url": "https://www.marblesystemstureks.com.tr/wp-content/uploads/2024/11/1356148.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 15),
                "announcement_source_url": "https://financialreports.eu/filings/tureks-turunc-madencilik-ic-ve-dis-ticaret-as/interim-quarterly-report/2026/46358097/",
            },
        ]

    def _fetch_alves_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 22),
                "announcement_source_url": "https://financialreports.eu/filings/alves-kablo-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6647228/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 30),
                "announcement_source_url": "https://financialreports.eu/filings/alves-kablo-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6623091/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/alves-kablo-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6613968/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 8),
                "announcement_source_url": "https://mbigpara.hurriyet.com.tr/kap-haberleri/alves-alves-kablo-sanayi-ve-ticaret-as-finansal-rapor/3491922",
            },
        ]

    def _fetch_obams_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 21),
                "announcement_source_url": "https://financialreports.eu/filings/oba-makarnacilik-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6647820/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 30),
                "announcement_source_url": "https://financialreports.eu/filings/oba-makarnacilik-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6623260/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 12, 11),
                "announcement_source_url": "https://financialreports.eu/filings/oba-makarnacilik-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6608856/",
            },
        ]

    def _fetch_artms_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/artemis-hali-as/interim-quarterly-report/2024/6650970/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 20),
                "announcement_source_url": "https://financialreports.eu/filings/artemis-hali-as/interim-quarterly-report/2024/6625789/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/artemis-hali-as/interim-quarterly-report/2024/6618195/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 2),
                "announcement_source_url": "https://financialreports.eu/filings/artemis-hali-as/interim-quarterly-report/2026/32865622/",
            },
        ]

    def _fetch_lmkdc_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 7, 9),
                "announcement_source_url": "https://financialreports.eu/filings/limak-dogu-anadolu-cimento-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6642084/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 19),
                "announcement_source_url": "https://financialreports.eu/filings/limak-dogu-anadolu-cimento-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6626365/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 25),
                "announcement_source_url": "https://financialreports.eu/filings/limak-dogu-anadolu-cimento-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6611703/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 2),
                "announcement_source_url": "https://financialreports.eu/filings/limak-dogu-anadolu-cimento-sanayi-ve-ticaret-as/interim-quarterly-report/2026/32865622/",
            },
        ]

    def _fetch_oylum_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/04/Finansal-Rapor-2023-2.-3-Aylik.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/04/Finansal-Rapor-2023-3.-3-Aylik.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 9),
                "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/11/Finansal-Raporu-2023-4.-3-Aylik.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/11/Finansal-Raporu-2024-1.-3-Aylik.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 20),
                "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/11/Finansal-Raporu-2024-2.-3-Aylik.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 10, 30),
                "announcement_source_url": "https://www.oylum.com/wp-content/uploads/2025/11/Finansal-Raporu-2024-3.-3-Aylik.pdf",
            },
        ]

    def _fetch_ozsub_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 12, 12),
                "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2023/12/Ozsu-30.06.2023-Finansal-Rapor.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 12, 12),
                "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2023/12/Ozsu-Rapor-30.09.2023-.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 21),
                "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2024/05/31.12.2023-Finansal-Rapor-3.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 14),
                "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2024/06/31.03.2024-Ozsu-Finansal-Rapor.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 27),
                "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2024/09/30.06.2024-Finansal-Rapor.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 12),
                "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2024/11/Ozsu-SPK-Rapor-30.09.2024-1.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 8),
                "announcement_source_url": "https://ozsubalik.com.tr/wp-content/uploads/2026/05/Finansal-Rapor-31.03.2026.pdf",
            },
        ]

    def _fetch_tezol_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 5, 10),
                "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2023/6736489/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 21),
                "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2023/6715156/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2023/6701763/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 9),
                "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2024/6663990/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 21),
                "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2024/6647614/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 6),
                "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2024/6629686/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/europap-tezol-kagit-sanayi-ve-ticaret-as/report-publication-announcement/2024/6614783/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 11),
                "announcement_source_url": "https://www.tezol.com.tr/wp-content/uploads/2026/05/EUROPAP-TEZOL-31.03.2026-SPK.pdf",
            },
        ]

    def _fetch_ozysr_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 20),
                "announcement_source_url": "https://financialreports.eu/filings/ozyasar-tel/report-publication-announcement/2024/6625377/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/ozyasar-tel/report-publication-announcement/2024/6614996/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 12, 1),
                "announcement_date": date(2025, 3, 8),
                "announcement_source_url": "https://financialreports.eu/filings/ozyasar-tel/report-publication-announcement/2025/6588403/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2025, 3, 1),
                "announcement_date": date(2025, 5, 9),
                "announcement_source_url": "https://financialreports.eu/filings/ozyasar-tel/report-publication-announcement/2025/6565244/",
            },
        ]

    def _fetch_vangd_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://financialreports.eu/filings/vanet-gida-sanayi-ic-ve-dis-ticaret-as/regulatory-filings/2023/6718729/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 28),
                "announcement_source_url": "https://financialreports.eu/filings/vanet-gida-sanayi-ic-ve-dis-ticaret-as/regulatory-filings/2023/6704684/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 4),
                "announcement_source_url": "https://financialreports.eu/filings/vanet-gida-sanayi-ic-ve-dis-ticaret-as/report-publication-announcement/2024/6616743/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 2),
                "announcement_source_url": "https://financialreports.eu/filings/vanet-gida-sanayi-ic-ve-dis-ticaret-as/report-publication-announcement/2026/32865598/",
            },
        ]

    def _fetch_merko_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 5, 10),
                "announcement_source_url": "https://financialreports.eu/filings/merko-gida-sanayi-ve-ticaret-as/audit-report-information/2023/6736589/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 9, 8),
                "announcement_source_url": "https://financialreports.eu/filings/merko-gida-sanayi-ve-ticaret-as/report-publication-announcement/2023/6711992/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/merko-gida-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6700592/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 3, 26),
                "announcement_source_url": "https://financialreports.eu/filings/6676061/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 5, 22),
                "announcement_source_url": "https://financialreports.eu/filings/6658520/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 11, 18),
                "announcement_source_url": "https://financialreports.eu/filings/6612771/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 12, 23),
                "announcement_source_url": "https://financialreports.eu/filings/6607269/content/",
            },
        ]

    def _fetch_mrshl_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 4),
                "announcement_source_url": "https://financialreports.eu/filings/6720785/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/marshall-boya-ve-vernik-sanayii-as/report-publication-announcement/2023/6704934/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 6),
                "announcement_source_url": "https://financialreports.eu/filings/6665924/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/6651072/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 19),
                "announcement_source_url": "https://financialreports.eu/filings/marshall-boya-ve-vernik-sanayii-as/report-publication-announcement/2024/6626352/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/marshall-boya-ve-vernik-sanayii-as/report-publication-announcement/2024/6617655/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 30),
                "announcement_source_url": "https://financialreports.eu/filings/marshall-boya-ve-vernik-sanayii-as/regulatory-filings/2026/39129203/",
            },
        ]

    def _fetch_samat_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 8),
                "announcement_source_url": "https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2023/6719858/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2023/6704149/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 6),
                "announcement_source_url": "https://financialreports.eu/filings/6665924/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 12),
                "announcement_source_url": "https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2024/6650465/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 11, 19),
                "announcement_source_url": "https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2024/6612572/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 29),
                "announcement_source_url": "https://financialreports.eu/filings/saray-matbaacilik-kagitcilik-kirtasiyecilik-ticaret-ve-sanayi-as/report-publication-announcement/2024/6610762/",
            },
        ]

    def _fetch_sarky_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 21),
                "announcement_source_url": "https://financialreports.eu/filings/sarkuysan-elektrolitik-bakir-sanayi-ve-ticaret-as/report-publication-announcement/2023/6715002/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 6),
                "announcement_source_url": "https://financialreports.eu/filings/6666038/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 14),
                "announcement_source_url": "https://financialreports.eu/filings/sarkuysan-elektrolitik-bakir-sanayi-ve-ticaret-as/report-publication-announcement/2024/6648967/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 27),
                "announcement_source_url": "https://financialreports.eu/filings/sarkuysan-elektrolitik-bakir-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6623902/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/6614168/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 11),
                "announcement_source_url": "https://financialreports.eu/filings/sarkuysan-elektrolitik-bakir-sanayi-ve-ticaret-as/interim-quarterly-report/2026/44977803/",
            },
        ]

    def _fetch_sayas_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6702104/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2023/6716668/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 9),
                "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/annual-report/2024/6666516/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6652195/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 13),
                "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6624002/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/say-yenilenebilir-enerji-ekipmanlari-sanayi-ve-ticaret-as/report-publication-announcement/2024/6614010/",
            },
        ]

    def _fetch_snica_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2023/6718096/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2023/6704663/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 4, 15),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2024/6671987/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2024/6650031/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 13),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2024/6625373/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2024/6618266/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 2),
                "announcement_source_url": "https://financialreports.eu/filings/sanica-isi-sanayi-as/report-publication-announcement/2026/32865891/",
            },
        ]

    def _fetch_rtalb_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 3, 1),
                "announcement_date": date(2023, 5, 8),
                "announcement_source_url": "https://financialreports.eu/filings/rta-laboratuvarlari-biyolojik-urunler-ilac-ve-makine-sanayi-ticaret-as/report-publication-announcement/2023/6737777/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://financialreports.eu/filings/rta-laboratuvarlari-biyolojik-urunler-ilac-ve-makine-sanayi-ticaret-as/report-publication-announcement/2023/6719358/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/rta-laboratuvarlari-biyolojik-urunler-ilac-ve-makine-sanayi-ticaret-as/report-publication-announcement/2023/6704659/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 10),
                "announcement_source_url": "https://financialreports.eu/filings/rta-laboratuvarlari-biyolojik-urunler-ilac-ve-makine-sanayi-ticaret-as/report-publication-announcement/2024/6662761/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://financialreports.eu/filings/rta-laboratuvarlari-biyolojik-urunler-ilac-ve-makine-sanayi-ticaret-as/report-publication-announcement/2024/6650039/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 18),
                "announcement_source_url": "https://financialreports.eu/filings/rta-laboratuvarlari-biyolojik-urunler-ilac-ve-makine-sanayi-ticaret-as/report-publication-announcement/2024/6626647/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 21),
                "announcement_source_url": "https://financialreports.eu/filings/rta-laboratuvarlari-biyolojik-urunler-ilac-ve-makine-sanayi-ticaret-as/report-publication-announcement/2024/6617100/",
            },
        ]

    def _fetch_yksln_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2023/6719259/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2023/6704472/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 10),
                "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2024/6663241/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 21),
                "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2024/6647830/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 30),
                "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2024/6623547/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/yukselen-celik-as/interim-quarterly-report/2024/6614247/",
            },
        ]

    def _fetch_oyakc_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 7),
                "announcement_source_url": "https://financialreports.eu/filings/oyak-cimento-fabrikalar-as/regulatory-filings/2026/43199204/",
            },
        ]

    def _fetch_banvt_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 5, 4),
                "announcement_source_url": "https://www.banvit.com/sites/default/files/2026-05/banvit-finansal-rapor-31.03.2026-turkce.pdf",
            },
        ]

    def _fetch_tborg_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 21),
                "announcement_source_url": "https://financialreports.eu/filings/6714890/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/report-publication-announcement/2023/6700830/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 6),
                "announcement_source_url": "https://financialreports.eu/filings/6665785/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 21),
                "announcement_source_url": "https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/regulatory-filings/2024/6647524/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 13),
                "announcement_source_url": "https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/interim-report/2024/6627824/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 7),
                "announcement_source_url": "https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/report-publication-announcement/2024/6615827/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 31),
                "announcement_source_url": "https://financialreports.eu/filings/turk-tuborg-bira-ve-malt-sanayii-as/regulatory-filings/2026/33118400/",
            },
        ]

    def _fetch_bfren_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6718492/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2023/6704538/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 7),
                "announcement_source_url": "https://financialreports.eu/filings/6665215/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 7, 12),
                "announcement_source_url": "https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6641734/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 20),
                "announcement_source_url": "https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6625381/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 13),
                "announcement_source_url": "https://financialreports.eu/filings/bosch-fren-sistemleri-sanayi-ve-ticaret-as/report-publication-announcement/2024/6613442/",
            },
        ]

    def _fetch_ozrdn_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2020, 3, 1),
                "announcement_date": date(2020, 5, 27),
                "announcement_source_url": "https://financialreports.eu/filings/ozerden-ambalaj-sanayi-as/regulatory-filings/2020/6938454/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2020, 9, 1),
                "announcement_date": date(2020, 11, 4),
                "announcement_source_url": "https://financialreports.eu/filings/ozerden-ambalaj-sanayi-as/report-publication-announcement/2020/6915323/",
            },
        ]

    def _fetch_uluun_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 14),
                "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6649528/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 17),
                "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/annual-quarterly-financial-statement/2023/6716336/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/interim-quarterly-report/2023/6701746/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 18),
                "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/annual-report/2024/6660299/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 12),
                "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6624184/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 8),
                "announcement_source_url": "https://financialreports.eu/filings/6615226/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 22),
                "announcement_source_url": "https://financialreports.eu/filings/ulusoy-un-sanayi-ve-ticaret-as/interim-quarterly-report/2026/35432866/",
            },
        ]

    def _fetch_yaprk_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 21),
                "announcement_source_url": "https://financialreports.eu/filings/6714835/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://financialreports.eu/filings/6701076/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 18),
                "announcement_source_url": "https://financialreports.eu/filings/yaprak-sut-ve-besi-ciftlikleri-sanayi-ve-ticaret-as/annual-report/2024/6660328/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 5, 22),
                "announcement_source_url": "https://financialreports.eu/filings/6658495/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 13),
                "announcement_source_url": "https://financialreports.eu/filings/6627597/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/6613905/content/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 11),
                "announcement_source_url": "https://financialreports.eu/filings/yaprak-sut-ve-besi-ciftlikleri-sanayi-ve-ticaret-as/report-publication-announcement/2026/32931112/",
            },
        ]

    def _fetch_yunsa_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 4, 17),
                "announcement_source_url": "https://financialreports.eu/filings/yunsa-yunlu-sanayi-ve-ticaret-as/regulatory-filings/2026/34659872/",
            },
        ]

    def _fetch_tukas_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 16),
                "announcement_source_url": "https://www.kap.org.tr/tr/Bildirim/1186172",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 6),
                "announcement_source_url": "https://www.bloomberght.com/borsa/hisse/tukas/kap-haberi/325401",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 9),
                "announcement_source_url": "https://www.kap.org.tr/tr/api/BildirimPdf/1284527",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 5, 22),
                "announcement_source_url": "https://financialreports.eu/filings/tukas-gda-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6658096/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 12),
                "announcement_source_url": "https://financialreports.eu/filings/tukas-gda-sanayi-ve-ticaret-as/interim-report/2024/6628304/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 11),
                "announcement_source_url": "https://financialreports.eu/filings/tukas-gda-sanayi-ve-ticaret-as/interim-quarterly-report/2024/6614015/",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2026, 3, 1),
                "announcement_date": date(2026, 3, 2),
                "announcement_source_url": "https://financialreports.eu/filings/tukas-gda-sanayi-ve-ticaret-as/report-publication-announcement/2026/32866801/",
            },
        ]

    def _fetch_tuclk_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 9),
                "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/spk-finansal-raporlar-2023-q2_4763.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 10, 30),
                "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/spk-finansal-raporlar-2023-q3_6577.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 9),
                "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/spk-finansal-raporlar-2023-q4_2609.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 11),
                "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/tugcelik-31032024-raporu_1385.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 20),
                "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/tugcelik-30-06-2024-raporu.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 7),
                "announcement_source_url": "https://www.tugcelik.com.tr/tr/pdf/30.09.2024-konsolide-olmayan-finansal-durum-raporu.pdf",
            },
        ]

    def _fetch_maktk_records(self, symbol: str) -> list[dict]:
        return [
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 6, 1),
                "announcement_date": date(2023, 8, 16),
                "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/16082023051957330.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 9, 1),
                "announcement_date": date(2023, 11, 9),
                "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/09112023053414288.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2023, 12, 1),
                "announcement_date": date(2024, 5, 3),
                "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/03052024201357505.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 3, 1),
                "announcement_date": date(2024, 6, 13),
                "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/13062024051216567.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 6, 1),
                "announcement_date": date(2024, 9, 18),
                "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/18092024180950962.pdf",
            },
            {
                "symbol": symbol.upper(),
                "period_end": date(2024, 9, 1),
                "announcement_date": date(2024, 11, 7),
                "announcement_source_url": "https://makinatakim.com.tr/wp-content/uploads/2026/01/07112024053903283.pdf",
            },
        ]

    def _fetch_safkr_records(self, symbol: str) -> list[dict]:
        endpoint = "https://webservisry.safkar.com/safkarAPI/investorRelations/list?limit=200"
        response = self._request("GET", endpoint, verify_ssl=False, data=None)
        try:
            payload = response.json()
        except Exception as error:
            raise ValueError("Could not parse SAFKR investor relations API payload") from error

        sections = payload.get("data", {}).get("investorRelations") or []
        disclosure_section = next((section for section in sections if section.get("title") == "Özel Durum Açıklamaları"), None)
        if disclosure_section is None:
            return []

        by_period: dict[date, dict] = {}
        pending_by_date: dict[date, list[dict]] = {}
        for item in disclosure_section.get("items") or []:
            title = str(item.get("title") or "")
            url = str(item.get("url") or "")
            announcement_date = _coerce_iso_or_date(item.get("date"))
            if announcement_date is None or not url:
                continue
            if not any(keyword in title.lower() for keyword in ("faaliyet raporu", "mali tablo", "finansal rapor", "konsolide mali tablo")):
                continue
            record = {
                "symbol": symbol.upper(),
                "announcement_date": announcement_date,
                "announcement_source_url": url,
                "title": title,
            }
            period_end = _extract_period_end(title)
            if period_end is not None:
                candidate = {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": url,
                }
                existing = by_period.get(period_end)
                if existing is None or announcement_date < existing["announcement_date"]:
                    by_period[period_end] = candidate
                for pending in pending_by_date.pop(announcement_date, []):
                    pending_candidate = {
                        "symbol": symbol.upper(),
                        "period_end": period_end,
                        "announcement_date": announcement_date,
                        "announcement_source_url": pending["announcement_source_url"],
                    }
                    existing = by_period.get(period_end)
                    if existing is None or announcement_date < existing["announcement_date"]:
                        by_period[period_end] = pending_candidate
            else:
                pending_by_date.setdefault(announcement_date, []).append(record)

        return list(by_period.values())

    def _fetch_hatek_records(self, symbol: str, config: IssuerIRSourceConfig) -> list[dict]:
        candidate_urls = {
            date(2023, 3, 1): [
                "https://www.hateks.com.tr/pdf/31-03-2023-BAGIMSIZ-DENETIM-RAPORU.pdf",
                "https://www.hateks.com.tr/pdf/31-03-2023-FAALIYET-RAPORU.pdf",
            ],
            date(2023, 6, 1): [
                "https://www.hateks.com.tr/pdf/30-06-2023-BAGIMSIZ-DENETIM-RAPORU.pdf",
            ],
            date(2023, 9, 1): [
                "https://www.hateks.com.tr/pdf/30-09-2023-BAGIMSIZ-DENETIM-RAPORU.pdf",
            ],
            date(2023, 12, 1): [
                "https://www.hateks.com.tr/pdf/31-12-2023-BAGIMSIZ-DENETIM-RAPORU.pdf",
            ],
            date(2024, 3, 1): [
                "https://www.hateks.com.tr/pdf/31-03-2024-BAGIMSIZ-DENETIM-RAPORU.pdf",
            ],
            date(2024, 6, 1): [
                "https://www.hateks.com.tr/pdf/30-06-2024-BAGIMSIZ-DENETIM-RAPORU.pdf",
            ],
            date(2024, 9, 1): [
                "https://www.hateks.com.tr/pdf/30-09-2024-BAGIMSIZ-DENETIM-RAPORU.pdf",
            ],
            date(2026, 3, 1): [
                "https://www.hateks.com.tr/pdf/31-03-2026-BAGIMSIZ-DENETIM-RAPORU.pdf",
                "https://www.hateks.com.tr/pdf/31-03-2026-FAALIYET-RAPORU.pdf",
            ],
        }
        records: list[dict] = []
        for period_end, urls in candidate_urls.items():
            for url in urls:
                try:
                    announcement_date = self._resolve_publication_date(url, verify_ssl=config.verify_ssl)
                except Exception:
                    continue
                if announcement_date is None:
                    continue
                if not _publication_date_within_lag(period_end, announcement_date, config.max_publication_lag_days):
                    continue
                records.append(
                    {
                        "symbol": symbol.upper(),
                        "period_end": period_end,
                        "announcement_date": announcement_date,
                        "announcement_source_url": url,
                    }
                )
                break
        manual_financialreports_periods = {
            "https://financialreports.eu/filings/hateks-hatay-tekstil-isletmeleri-as/report-publication-announcement/2023/6700875/": date(2023, 9, 1),
            "https://financialreports.eu/filings/hateks-hatay-tekstil-isletmeleri-as/report-publication-announcement/2024/6648801/": date(2024, 3, 1),
            "https://financialreports.eu/filings/hateks-hatay-tekstil-isletmeleri-as/interim-quarterly-report/2024/6623064/": date(2024, 6, 1),
            "https://financialreports.eu/filings/hateks-hatay-tekstil-isletmeleri-as/report-publication-announcement/2024/6615426/": date(2024, 9, 1),
        }
        for page_url, period_end in manual_financialreports_periods.items():
            try:
                html = self._request_text(page_url)
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            announcement_date = _extract_financialreports_published_date(soup)
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": page_url,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_financialreports_records(self, symbol: str, config: IssuerIRSourceConfig) -> list[dict]:
        records: list[dict] = []
        for page_url in self._page_urls_for_config(config):
            html = self._request_text(page_url, verify_ssl=config.verify_ssl)
            record = self._parse_financialreports_page(symbol, html, page_url)
            if record is not None:
                records.append(record)
        return _deduplicate_records_by_earliest_announcement(records)

    def _fetch_selva_records(self, symbol: str, config: IssuerIRSourceConfig) -> list[dict]:
        endpoint = "https://www.selva.com.tr/InvestorRelations/GetFilterByYearwType"
        records: list[dict] = []
        current_year = datetime.now(UTC).year
        for year in range(current_year, 2020, -1):
            payload = {"year": str(year), "typeID": "2"}
            response = self._request("POST", endpoint, verify_ssl=config.verify_ssl, data=payload)
            try:
                items = response.json()
            except Exception:
                continue
            if not isinstance(items, list):
                continue
            for item in items:
                finance_name = str(item.get("financeName") or "")
                finance_file = str(item.get("financeFile") or "")
                finance_id = item.get("financeID")
                finance_date = item.get("financeDate")
                period_end = _extract_period_end(f"{finance_name} {finance_file}")
                announcement_date = parsedate_to_date(str(finance_date)) if finance_date else None
                if period_end is None or announcement_date is None or finance_id in (None, "") or not finance_file:
                    continue
                href = f"https://admin.selva.com.tr/Files/Finans/{finance_id}/{finance_file}"
                records.append(
                    {
                        "symbol": symbol.upper(),
                        "period_end": period_end,
                        "announcement_date": announcement_date,
                        "announcement_source_url": href,
                    }
                )
        return _deduplicate_records_by_earliest_announcement(records)

    def parse_html(self, symbol: str, html: str, source_url: str, verify_ssl: bool = True) -> list[dict]:
        if "fadegida.com.tr" in source_url:
            return self._parse_fade_html(symbol, html, verify_ssl=verify_ssl)
        if "izyatirimholding.com" in source_url:
            return self._parse_izinv_html(symbol, html, verify_ssl=verify_ssl)
        if "frigo-pak.com.tr" in source_url:
            return self._parse_frigo_html(symbol, html, source_url, verify_ssl=verify_ssl)
        if "sekuro.com.tr" in source_url:
            return self._parse_sekur_html(symbol, html, source_url, verify_ssl=verify_ssl)
        if "ruzymadencilik.com.tr" in source_url:
            return self._parse_ruzye_html(symbol, html, source_url, verify_ssl=verify_ssl)
        if "marblesystemstureks.com.tr" in source_url:
            return self._parse_marbl_html(symbol, html, source_url)
        if "rtalabs.com.tr" in source_url and "ozel-durum-aciklamalari" in source_url:
            return self._parse_rtalb_disclosures_html(symbol, html)
        soup = BeautifulSoup(html, "html.parser")
        config = ISSUER_IR_SOURCES.get(symbol.upper(), IssuerIRSourceConfig(symbol=symbol.upper(), page_url=source_url))
        records: list[dict] = []
        for anchor in soup.find_all("a", href=True):
            href = _normalize_document_url(urljoin(source_url, anchor["href"]))
            text = " ".join(anchor.get_text(" ", strip=True).split())
            title_text = " ".join(str(anchor.get("title", "")).split())
            context_text = _extract_anchor_context_text(anchor, text)
            combined_text = " ".join(part for part in [text, title_text, context_text] if part)
            if not _looks_like_financial_document(text=combined_text, href=href, keywords=config.document_keywords):
                continue
            period_end = _extract_period_end(f"{combined_text} {href}")
            if period_end is None:
                continue
            try:
                announcement_date = self._resolve_publication_date(href, verify_ssl=verify_ssl)
            except Exception:
                continue
            if announcement_date is None:
                continue
            if not _publication_date_within_lag(period_end, announcement_date, config.max_publication_lag_days):
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": href,
                }
            )
        return records

    def _parse_sekur_html(self, symbol: str, html: str, source_url: str, verify_ssl: bool = True) -> list[dict]:
        config = ISSUER_IR_SOURCES[symbol.upper()]
        matches = re.findall(
            r'<a\s+href="([^"]*?/uploads/[^"]+\.pdf)"[^>]*>(.*?)</a>',
            html,
            re.I | re.S,
        )
        records: list[dict] = []
        for href, inner_html in matches:
            clean_label = " ".join(BeautifulSoup(inner_html, "html.parser").get_text(" ", strip=True).split())
            normalized_href = _normalize_document_url(urljoin(source_url, href))
            if not _looks_like_financial_document(
                text=clean_label,
                href=normalized_href,
                keywords=config.document_keywords,
            ):
                continue
            period_end = _extract_period_end(f"{clean_label} {normalized_href}")
            if period_end is None:
                continue
            try:
                announcement_date = self._resolve_publication_date(normalized_href, verify_ssl=verify_ssl)
            except Exception:
                continue
            if announcement_date is None:
                continue
            if not _publication_date_within_lag(period_end, announcement_date, config.max_publication_lag_days):
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": normalized_href,
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _parse_marbl_html(self, symbol: str, html: str, source_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict] = []
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            anchor = row.find("a", href=True)
            if len(cells) < 3 or anchor is None:
                continue
            label = " ".join(cells[0].get_text(" ", strip=True).split())
            date_text = " ".join(cells[1].get_text(" ", strip=True).split())
            href = _normalize_document_url(urljoin(source_url, anchor["href"]))
            if not _looks_like_financial_document(label, href, keywords=FINANCIAL_KEYWORDS):
                continue
            period_end = _extract_marbl_period_end(label) or _extract_period_end(f"{label} {href}")
            announcement_date = parsedate_to_date(date_text)
            if period_end is None or announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": href,
                }
            )
        return records

    def _parse_rtalb_disclosures_html(self, symbol: str, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict] = []
        for heading in soup.find_all(["h6", "h5", "h4"]):
            title = " ".join(heading.get_text(" ", strip=True).split())
            if "finansal rapor" not in title.lower():
                continue
            match = re.match(r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(.+)", title)
            if match is None:
                continue
            announcement_date = parsedate_to_date(match.group(1))
            remainder = match.group(2)
            period_end = _extract_period_end(remainder)
            if announcement_date is None or period_end is None:
                continue
            container = heading.find_parent()
            anchor = container.find_next("a", href=True) if container is not None else None
            if anchor is None:
                continue
            href = _normalize_document_url(anchor["href"])
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": href,
                }
            )
        return records

    def _parse_frigo_html(self, symbol: str, html: str, source_url: str, verify_ssl: bool = True) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict] = []
        for anchor in soup.find_all("a", href=True):
            href = _normalize_document_url(urljoin(source_url, anchor["href"]))
            text = " ".join(anchor.get_text(" ", strip=True).split())
            if not _looks_like_financial_document(text=text, href=href):
                continue
            period_end = _extract_period_end(f"{text} {href}")
            if period_end is None:
                continue
            # The site bulk re-uploaded later 2023/2024 reports in December 2024.
            # Only keep the pre-bulk-upload documents whose publication dates still
            # look like original disclosures.
            if "/2024/12/" in href:
                continue
            try:
                announcement_date = self._resolve_publication_date(href, verify_ssl=verify_ssl)
            except Exception:
                continue
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": href,
                }
            )
        return records

    def _parse_ruzye_html(self, symbol: str, html: str, source_url: str, verify_ssl: bool = True) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        config = ISSUER_IR_SOURCES[symbol.upper()]
        records: list[dict] = []
        for anchor in soup.find_all("a", href=True):
            href = _normalize_document_url(urljoin(source_url, anchor["href"]))
            text = " ".join(anchor.get_text(" ", strip=True).split())
            if not _looks_like_financial_document(text=text, href=href, keywords=config.document_keywords):
                continue
            period_end = _extract_period_end(f"{text} {href}")
            if period_end is None:
                continue
            try:
                announcement_date = self._resolve_publication_date(href, verify_ssl=verify_ssl)
            except Exception:
                continue
            if announcement_date is None:
                continue
            if not _publication_date_within_lag(period_end, announcement_date, config.max_publication_lag_days):
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": href,
                }
            )
        return records

    def _parse_fade_html(self, symbol: str, html: str, verify_ssl: bool = True) -> list[dict]:
        section_match = re.search(
            r"Finansal Tablolar(?P<section>.*?)(?:Faaliyet Raporlar|Genel Kurul|$)",
            html,
            re.I | re.S,
        )
        if section_match is None:
            return []
        section = section_match.group("section")
        matches = re.findall(
            r'href="([^"]+)"[^>]*>\s*((?:31|30)\.\d{2}\.20\d{2})\s*<',
            section,
            re.I,
        )
        records: list[dict] = []
        for href, label in matches:
            period_end = _extract_period_end(label)
            if period_end is None:
                continue
            try:
                announcement_date = self._resolve_publication_date(href, verify_ssl=verify_ssl)
            except Exception:
                continue
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": href,
                }
            )
        return records

    def _parse_izinv_html(self, symbol: str, html: str, verify_ssl: bool = True) -> list[dict]:
        matches = re.findall(
            r"(\d{2}\s*/\s*20\d{2}\s*Finansal Rapor).{0,800}?href=\"([^\"]+\.pdf)\"",
            html,
            re.I | re.S,
        )
        records: list[dict] = []
        for label, href in matches:
            period_end = _extract_period_end(label)
            if period_end is None:
                continue
            try:
                announcement_date = self._resolve_publication_date(href, verify_ssl=verify_ssl)
            except Exception:
                continue
            if announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": href,
                }
            )
        return records

    def _parse_kayse_html(self, symbol: str, html: str, source_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict] = []
        for item in soup.select("div.item"):
            anchor = item.select_one("a[href]")
            title_node = item.select_one(".title")
            date_node = item.select_one(".date")
            if anchor is None or title_node is None or date_node is None:
                continue
            title = " ".join(title_node.get_text(" ", strip=True).split())
            if not _looks_like_financial_document(title, anchor["href"]):
                continue
            period_end = _extract_kayse_period_end(title)
            announcement_date = parsedate_to_date(date_node.get_text(" ", strip=True))
            if period_end is None or announcement_date is None:
                continue
            records.append(
                {
                    "symbol": symbol.upper(),
                    "period_end": period_end,
                    "announcement_date": announcement_date,
                    "announcement_source_url": _normalize_document_url(urljoin(source_url, anchor["href"])),
                }
            )
        return _deduplicate_records_by_earliest_announcement(records)

    def _parse_financialreports_page(self, symbol: str, html: str, source_url: str) -> dict | None:
        soup = BeautifulSoup(html, "html.parser")
        text = _extract_financialreports_primary_text(soup)
        period_end = _extract_financialreports_period_end(text)
        announcement_date = _extract_financialreports_published_date(soup)
        if period_end is None or announcement_date is None:
            return None
        return {
            "symbol": symbol.upper(),
            "period_end": period_end,
            "announcement_date": announcement_date,
            "announcement_source_url": source_url,
        }

    def _page_urls_for_config(self, config: IssuerIRSourceConfig) -> list[str]:
        if not config.year_param:
            return [config.page_url, *config.extra_page_urls]
        current_year = datetime.now(UTC).year
        first_year = config.first_year or current_year
        param_name = config.year_param_name or "year"
        pages = [f"{config.page_url}?{param_name}={year}" for year in range(current_year, first_year - 1, -1)]
        pages.extend(config.extra_page_urls)
        return pages

    def _resolve_publication_date(self, document_url: str, verify_ssl: bool = True) -> date | None:
        response = self._request("HEAD", document_url, verify_ssl=verify_ssl)
        last_modified = response.headers.get("Last-Modified")
        if last_modified:
            parsed = parsedate_to_date(last_modified)
            if parsed is not None:
                return parsed
        query_timestamp = _query_timestamp_to_date(document_url)
        if query_timestamp is not None:
            return query_timestamp
        return None

    def _request_text(self, url: str, verify_ssl: bool = True) -> str:
        response = self._request("GET", url, verify_ssl=verify_ssl)
        return response.text

    def _request(self, method: str, url: str, verify_ssl: bool = True, data: dict | None = None):
        self._respect_request_interval()
        with warnings.catch_warnings():
            if not verify_ssl:
                warnings.simplefilter("ignore", InsecureRequestWarning)
            response = requests.request(
                method,
                url,
                data=data,
                timeout=self.request_timeout_seconds,
                headers=REQUEST_HEADERS,
                allow_redirects=True,
                verify=verify_ssl,
            )
        self._last_request_monotonic = time.monotonic()
        response.raise_for_status()
        return response

    def _respect_request_interval(self) -> None:
        elapsed = time.monotonic() - self._last_request_monotonic
        remaining = self.min_request_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)


def parsedate_to_date(value: str) -> date | None:
    compact = " ".join(str(value).split())
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", compact):
        try:
            return datetime.strptime(compact, "%d.%m.%Y").date()
        except ValueError:
            return None
    try:
        return pd.to_datetime(value, utc=True).date()
    except Exception:
        return None


def _coerce_iso_or_date(value: str | None) -> date | None:
    if value in (None, ""):
        return None
    try:
        return pd.to_datetime(value, utc=True).date()
    except Exception:
        return parsedate_to_date(str(value))


def _looks_like_financial_document(text: str, href: str, keywords: tuple[str, ...] = FINANCIAL_KEYWORDS) -> bool:
    haystack = f"{text} {href}".lower()
    return any(keyword in haystack for keyword in keywords)


def _normalize_document_url(url: str) -> str:
    parts = urlsplit(url)
    normalized_path = unicodedata.normalize("NFC", parts.path)
    normalized_path = normalized_path.replace("/sayfa/images/", "/images/")
    return urlunsplit((parts.scheme, parts.netloc, normalized_path, parts.query, parts.fragment))


def _extract_period_end(value: str) -> date | None:
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = normalized.replace("_", ".").replace("-", ".").replace("/", ".")
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.combining(character)
    )

    match = re.search(r"\b(20\d{2})(03|06|09|12)(31|30|29|28)\b", folded)
    if match:
        return date(int(match.group(1)), int(match.group(2)), 1)

    match = re.search(r"\b(31|30|29|28)(03|06|09|12)(20\d{2})\b", folded)
    if match:
        return date(int(match.group(3)), int(match.group(2)), 1)

    for months, quarter_end_month in [(3, 3), (6, 6), (9, 9), (12, 12)]:
        match = re.search(rf"(20\d{{2}})\s*(?:yılı\s*)?{months}\s*aylık", folded)
        if match:
            return date(int(match.group(1)), quarter_end_month, 1)
        match = re.search(rf"{months}\s*aylık.*?(20\d{{2}})", folded)
        if match:
            return date(int(match.group(1)), quarter_end_month, 1)

    match = re.search(r"\b(20\d{2})\s*(?:yılı\s*)?([1-4])\.\s*3\s*aylık", folded)
    if match:
        return date(int(match.group(1)), int(match.group(2)) * 3, 1)
    match = re.search(r"\b([1-4])\.\s*3\s*aylık.*?(20\d{2})", folded)
    if match:
        return date(int(match.group(2)), int(match.group(1)) * 3, 1)

    match = re.search(r"\b(20\d{2})\s*yılı\b", folded)
    if match and any(keyword in folded for keyword in ("finansal", "mali", "denetim", "dipnot")):
        return date(int(match.group(1)), 12, 1)

    match = re.search(r"\b(20\d{2})\s*[\._ ]*([1-4])\s*[\._ ]*donem\b", folded)
    if match:
        return date(int(match.group(1)), int(match.group(2)) * 3, 1)
    match = re.search(r"\b([1-4])\s*[\._ ]*donem.*?(20\d{2})", folded)
    if match:
        return date(int(match.group(2)), int(match.group(1)) * 3, 1)

    match = re.search(r"\b(03|06|09|12)\s*\.\s*(20\d{2})\b", folded)
    if match:
        return date(int(match.group(2)), int(match.group(1)), 1)

    for month_name, month in TURKISH_MONTH_TO_QUARTER_END.items():
        match = re.search(rf"(20\d{{2}})\s*{month_name}", folded)
        if match:
            return date(int(match.group(1)), month, 1)
        match = re.search(rf"(31|30|29|28)\s*{month_name}\s*(20\d{{2}})", folded)
        if match:
            return date(int(match.group(2)), month, 1)

    match = re.search(r"(31|30|29|28)\.(03|06|09|12)\.(20\d{2})", folded)
    if match:
        return date(int(match.group(3)), int(match.group(2)), 1)

    match = re.search(r"(20\d{2})\.(03|06|09|12)\b", folded)
    if match:
        return date(int(match.group(1)), int(match.group(2)), 1)

    match = re.search(r"\b(03|06|09|12)\.(20\d{2})\b", folded)
    if match:
        return date(int(match.group(2)), int(match.group(1)), 1)

    match = re.search(r"\b(20\d{2})\s*(03|06|09|12)\b", folded)
    if match:
        return date(int(match.group(1)), int(match.group(2)), 1)

    return None


def _publication_date_within_lag(
    period_end: date,
    announcement_date: date,
    max_publication_lag_days: int | None,
) -> bool:
    if max_publication_lag_days is None:
        return True
    last_day = calendar.monthrange(period_end.year, period_end.month)[1]
    quarter_close = date(period_end.year, period_end.month, last_day)
    lag_days = (announcement_date - quarter_close).days
    return 0 <= lag_days <= max_publication_lag_days


def _deduplicate_records_by_earliest_announcement(records: list[dict]) -> list[dict]:
    deduplicated: dict[tuple[str, date], dict] = {}
    for record in records:
        key = (record["symbol"], record["period_end"])
        existing = deduplicated.get(key)
        if existing is None or record["announcement_date"] < existing["announcement_date"]:
            deduplicated[key] = record
    return list(deduplicated.values())


def _extract_financialreports_published_date(soup: BeautifulSoup) -> date | None:
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta is not None and meta.get("content"):
        return parsedate_to_date(str(meta["content"]))
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        script_text = script.string or script.get_text()
        if not script_text:
            continue
        match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', script_text)
        if match:
            return parsedate_to_date(match.group(1))
    return None


def _extract_financialreports_primary_text(soup: BeautifulSoup) -> str:
    text = " ".join(soup.get_text(" ", strip=True).split())
    start_markers = [
        "Open in Viewer",
        "Opens in native device viewer",
    ]
    for marker in start_markers:
        index = text.find(marker)
        if index != -1:
            text = text[index:]
            break
    end_markers = [
        "More from",
        "View all filings",
        "GET /api/companies/",
    ]
    for marker in end_markers:
        index = text.find(marker)
        if index != -1:
            text = text[:index]
    return text[:12000]


def _extract_financialreports_period_end(text: str) -> date | None:
    summary_match = re.search(
        r"Financial Statement Year / Period\s*(20\d{2})\s*/\s*(3|6|9|12)\s*Months",
        text,
        re.I,
    )
    if summary_match:
        year = int(summary_match.group(1))
        month = int(summary_match.group(2))
        return date(year, month, 1)

    summary_match = re.search(
        r"Financial Statement Year / Period\s*(20\d{2})\s*/\s*Annual",
        text,
        re.I,
    )
    if summary_match:
        return date(int(summary_match.group(1)), 12, 1)

    heading_match = re.search(
        r"\b1\s*OCAK\s*[-–]\s*30\s*(MART|HAZIRAN|EYLUL|EYLÜL|ARALIK)\s*(20\d{2})\b",
        text,
        re.I,
    )
    if heading_match:
        month = TURKISH_MONTH_TO_QUARTER_END[
            "".join(
                character
                for character in unicodedata.normalize("NFKD", heading_match.group(1).lower())
                if not unicodedata.combining(character)
            )
        ]
        return date(int(heading_match.group(2)), month, 1)

    return _extract_period_end(text)


def _query_timestamp_to_date(url: str) -> date | None:
    query = parse_qs(urlsplit(url).query)
    values = query.get("v") or []
    if not values:
        return None
    raw_value = values[0]
    if not raw_value.isdigit():
        return None
    try:
        timestamp = int(raw_value)
    except ValueError:
        return None
    if timestamp < 1_000_000_000:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).date()


def _extract_kayse_period_end(value: str) -> date | None:
    normalized = unicodedata.normalize("NFKC", value).lower()

    match = re.search(r"\b(20\d{2})\s*yılı\b", normalized)
    if match and "denetim raporu" in normalized:
        return date(int(match.group(1)), 12, 1)

    match = re.search(
        r"01\.05\.(20\d{2})\s*[-–]\s*31\.(01|07|10)\.(20\d{2}).*?([123])\.\s*çeyrek",
        normalized,
    )
    if match:
        start_year = int(match.group(1))
        end_month = int(match.group(2))
        quarter = int(match.group(4))
        if quarter == 1 and end_month == 7:
            return date(start_year, 3, 1)
        if quarter == 2 and end_month == 10:
            return date(start_year, 6, 1)
        if quarter == 3 and end_month == 1:
            return date(start_year, 9, 1)

    match = re.search(r"31\.10\.(20\d{2}).*?ara dönem", normalized)
    if match:
        return date(int(match.group(1)), 6, 1)

    return _extract_period_end(value)


def _extract_marbl_period_end(value: str) -> date | None:
    normalized = unicodedata.normalize("NFKC", value).lower()
    match = re.search(r"\b(20\d{2}).*?([1-4])\.\s*3\s*aylık", normalized)
    if match:
        return date(int(match.group(1)), int(match.group(2)) * 3, 1)
    return None


def _extract_anchor_context_text(anchor, text: str) -> str:
    context_text = text
    if text.upper() not in {"PDF", "İNDİR", "[İNDİR]", "DOWNLOAD"}:
        return context_text
    parent_context = _extract_same_parent_context(anchor)
    if parent_context is not None:
        return parent_context
    sibling_context = _extract_nearest_sibling_context(anchor)
    if sibling_context is not None:
        return sibling_context
    for node in list(anchor.parents)[:6]:
        candidate = " ".join(node.get_text(" ", strip=True).split())
        if _is_informative_context(candidate):
            return candidate
    return context_text


def _is_informative_context(value: str) -> bool:
    normalized = " ".join(value.split())
    if not normalized:
        return False
    if normalized.upper() in {"PDF", "İNDİR", "[İNDİR]", "DOWNLOAD"}:
        return False
    return bool(re.search(r"20\d{2}|mart|haziran|eyl|aralık|aralik|finansal|mali|rapor|tablo|aylık", normalized, re.I))


def _extract_nearest_sibling_context(anchor) -> str | None:
    parent = anchor.parent
    for _ in range(3):
        if parent is None:
            return None
        sibling_texts: list[str] = []
        for sibling in list(parent.previous_siblings)[-4:]:
            if hasattr(sibling, "get_text"):
                sibling_texts.append(" ".join(sibling.get_text(" ", strip=True).split()))
            else:
                sibling_texts.append(str(sibling).strip())
        combined = " ".join(part for part in sibling_texts if part)
        if _is_informative_context(combined):
            return combined
        parent = parent.parent
    return None


def _extract_same_parent_context(anchor) -> str | None:
    parent = anchor.parent
    if parent is None:
        return None
    candidate = " ".join(parent.get_text(" ", strip=True).split())
    if not _is_informative_context(candidate):
        return None
    if candidate.lower().count("download") > 1:
        return None
    return candidate
