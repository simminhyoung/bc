"""
.env 파일에서 API 키를 불러오는 설정 모듈
"""

import os
from dotenv import load_dotenv

load_dotenv()  # .env 파일을 읽어 환경변수로 등록

BITHUMB_ACCESS_KEY = os.getenv("BITHUMB_ACCESS_KEY")
BITHUMB_SECRET_KEY = os.getenv("BITHUMB_SECRET_KEY")
