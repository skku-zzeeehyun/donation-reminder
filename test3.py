import requests
import sqlite3
import json
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re

# SMTP 설정 (Gmail 예시)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "fund@g.skku.edu"  # 발신자 Gmail
SENDER_PASSWORD = "fzki bfis ukll iuir"  # Gmail 앱 비밀번호
TEAM_CONTACT = "성균관대학교 발전협력팀 02-760-1153/1159"  # 기부 팀 연락처

# 대상 월 설정
TARGET_YEAR_MONTH = "2025-05"  # 테스트용, 2025년 5월
# 동적 설정 예: 현재 월
# from datetime import datetime
# TARGET_YEAR_MONTH = datetime.now().strftime("%Y-%m")
# 또는 사용자 입력
# TARGET_YEAR_MONTH = input("대상 연월(YYYY-MM)을 입력하세요: ")

# SQLite 데이터베이스 설정
conn = sqlite3.connect("pledges.db")
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS pledges (
        MemberCode TEXT PRIMARY KEY,
        PledgeAmount INTEGER,
        Name TEXT,
        PledgeEndDate TEXT
    )
""")

# CSV에서 데이터 입력
try:
    pledge_df = pd.read_csv("pledges.csv")
    print("CSV 데이터:")
    print(pledge_df)
    # 데이터 전처리
    pledge_df["MemberCode"] = pledge_df["MemberCode"].astype(str).str.replace("\\.0$", "", regex=True)
    pledge_df["PledgeAmount"] = pledge_df["PledgeAmount"].astype(str).str.replace(",", "").astype(int)
    # PledgeEndDate를 YYYY-MM 형식으로 검증
    def validate_year_month(date_str):
        if not re.match(r"^\d{4}-\d{2}$", date_str):
            raise ValueError(f"잘못된 PledgeEndDate 형식: {date_str}, YYYY-MM 필요")
        return date_str
    pledge_df["PledgeEndDate"] = pledge_df["PledgeEndDate"].astype(str).apply(validate_year_month)
    print("전처리된 CSV 데이터:")
    print(pledge_df)
    pledge_df.to_sql("pledges", conn, if_exists="replace", index=False)
except FileNotFoundError:
    print("에러: pledges.csv 파일을 찾을 수 없습니다.")
    exit()
except KeyError as e:
    print(f"에러: CSV에 {e} 열이 없습니다. MemberCode, PledgeAmount, PledgeEndDate 확인.")
    exit()
except ValueError as e:
    print(f"에러: 데이터 형식이 잘못되었습니다. PledgeAmount(숫자)와 PledgeEndDate(YYYY-MM) 확인. {e}")
    exit()

# 약정액 데이터 읽기 (지정 월 종료된 약정만)
pledge_data = {}
cursor.execute("SELECT MemberCode, PledgeAmount, Name, PledgeEndDate FROM pledges WHERE PledgeEndDate = ?", (TARGET_YEAR_MONTH,))
for row in cursor.fetchall():
    pledge_data[row[0]] = {"PledgeAmount": row[1], "Name": row[2], "PledgeEndDate": row[3]}
print(f"{TARGET_YEAR_MONTH} 종료된 약정 데이터:", pledge_data)

# Donus API 설정
url_template = "https://cloud.donus.org/api/members/v0/member/code/{}?apikey=9331288A-FCD5-4108-B022-7989D82895DC"
member_codes = list(pledge_data.keys())  # 대상 월 종료된 MemberCode만

# 이메일 전송 함수
def send_email(recipient_email, recipient_name, pledge_amount, donation_amount, shortfall, pledge_end_date):
    subject = f"{recipient_name}님 발전기금 내역 안내드립니다."
    body = f"""
    안녕하세요, {recipient_name}님.

    성균관대학교 기부 캠페인에 참여해 주셔서 감사합니다.
    - 약정액: {pledge_amount:,}원
    - 현재 기부액: {donation_amount:,}원
    - 미납액: {shortfall:,}원

    약정 기간이 {pledge_end_date}에 종료되었습니다. 미납액을 납부해 주시면 캠페인 목표 달성에 큰 도움이 됩니다.
    문의: {TEAM_CONTACT}

    감사합니다,
    성균관대학교 발전협력팀
    """
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        print(f"이메일 전송 성공: {recipient_email}")
    except Exception as e:
        print(f"이메일 전송 실패: {recipient_email}, 에러: {e}")

# Donus API 요청 및 이메일 전송
results = []
for member_code in member_codes:
    url = url_template.format(member_code)
    payload = {}
    headers = {
        'Content-Type': 'application/json'
    }
    try:
        response = requests.request("GET", url, headers=headers, data=payload)
        print(f"Donus API Status for {member_code}: {response.status_code}")
        print(response.text)
        
        donation_data = json.loads(response.text)
        print(f"Response JSON for {member_code}:")
        print(json.dumps(donation_data, indent=2, ensure_ascii=False))
        donation_amount = donation_data.get("totalPrice", 0)
        
        pledge_amount = pledge_data[member_code]["PledgeAmount"]
        name = pledge_data[member_code]["Name"]
        pledge_end_date = pledge_data[member_code]["PledgeEndDate"]
        email = donation_data.get("email", "")
        shortfall = pledge_amount - donation_amount
        print(f"Member {member_code} ({name}): Pledge = {pledge_amount}, Donation = {donation_amount}, Shortfall = {shortfall}")
        
        # 부족분 있으면 이메일 전송
        if shortfall > 0 and email:
            send_email(email, name, pledge_amount, donation_amount, shortfall, pledge_end_date)
        
        # 결과 저장
        results.append([member_code, pledge_amount, donation_amount, shortfall, name, email, pledge_end_date])
    except requests.exceptions.RequestException as e:
        print(f"Donus API Error for {member_code}: {e}")
    except json.JSONDecodeError:
        print(f"Donus API Response not JSON for {member_code}: {response.text}")
    except TypeError as e:
        print(f"TypeError for {member_code}: {e}")

    import time
    time.sleep(0.5)

# 결과 CSV 저장
if results:
    pd.DataFrame(results, columns=["MemberCode", "PledgeAmount", "DonationAmount", "Shortfall", "Name", "Email", "PledgeEndDate"]).to_csv("results.csv", index=False)
    print("결과를 results.csv에 저장했습니다.")
else:
    print(f"{TARGET_YEAR_MONTH} 종료된 약정 없음, results.csv 생성 안 함.")

# DB 연결 종료
conn.close()