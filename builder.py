import os
import json
import urllib.request

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

print(f">>> API Key 접두사 확인: {API_KEY[:6]}... (정상 로드됨)")

# 1. 내 API 키로 사용 가능한 전체 모델 목록 조회 (ListModels)
list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"

print(">>> 구글 서버에 지원 모델 목록(ListModels) 요청 중...")
try:
    req = urllib.request.Request(list_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as res:
        data = json.loads(res.read().decode("utf-8"))
        models = data.get("models", [])
        
        print("\n================ [사용 가능한 모델 목록] ================")
        usable_models = []
        for m in models:
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods:
                name = m.get("name") # e.g. models/gemini-1.5-flash
                print(f"- {name}")
                usable_models.append(name)
        print("========================================================\n")

except urllib.error.HTTPError as e:
    err_body = e.read().decode("utf-8")
    print(f"!!! ListModels 실패 (HTTP {e.code}) !!!")
    print(f"구글 응답 본문: {err_body}")
    exit(1)

if not usable_models:
    print("generateContent를 지원하는 모델이 목록에 없습니다.")
    exit(1)

# 2. 첫 번째 발견된 정상 모델로 즉시 1건 테스트 호출
target_model = usable_models[0]
print(f">>> 감지된 지원 모델 [{target_model}]로 즉시 기사 생성 테스트 진행...")

test_url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={API_KEY}"
payload = {
    "contents": [{"parts": [{"text": "대한민국 자동차 매거진 카이슈 테스트 기사 한 문장만 써줘."}]}]
}

try:
    req_test = urllib.request.Request(
        test_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req_test, timeout=20) as test_res:
        res_json = json.loads(test_res.read().decode("utf-8"))
        reply = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
        print("\n>>> [성공!] 구글 AI 응답 확인:")
        print(reply)
        print("\n>>> 이 모델 식별자로 builder.py에 영구 고정하면 100% 끝납니다.")
except urllib.error.HTTPError as e:
    print(f"!!! 호출 실패: {e.read().decode('utf-8')}")
