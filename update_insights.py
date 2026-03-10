import os
import re
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

# 1. התחברות לבינה המלאכותית והגדרת מודל
api_key = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=api_key)

valid_model_name = None
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        valid_model_name = m.name
        break

if not valid_model_name:
    raise Exception("No suitable Gemini model found.")
model = genai.GenerativeModel(valid_model_name)

# 2. משיכת נתונים - עם "תחפושת" של דפדפן כרום אמיתי
try:
    url = "https://ibasketball.co.il/%D7%9C%D7%99%D7%92%D7%94-%D7%9C%D7%90%D7%95%D7%9E%D7%99%D7%AA-%D7%92%D7%91%D7%A8%D7%99%D7%9D/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    response = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    tables = soup.find_all('table')
    if tables:
        standings_text = tables[0].get_text(separator=" | ", strip=True)
    else:
        standings_text = "ERROR"
except Exception as e:
    standings_text = "ERROR"

# 3. מנגנון הגנה - אם אין נתונים, אל תבקש חפירה מה-AI
if standings_text == "ERROR" or len(standings_text) < 100:
    new_insights = "<p>ממתין לעדכון נתונים משרתי איגוד הכדורסל...</p>"
else:
    # 4. בקשת המסקנות מהבינה המלאכותית
    prompt = f"""
    אתה פרשן סטטיסטי של כדורסל. להלן נתונים גולמיים שנמשכו כרגע מטבלת הליגה הלאומית:
    {standings_text}

    כתוב 3 פסקאות קצרות ומקצועיות של מסקנות סטטיסטיות על מצבה של קבוצת 'מכבי רחובות'.
    התייחס למאבק על המקום ה-1, ליתרון הביתיות (מקומות 1-4) ולסכנות לקראת הפלייאוף.
    אל תנחש, תתבסס רק על מתמטיקה.
    חובה להשתמש בתגיות HTML של <p> ו-<strong> בלבד.
    אל תוסיף כותרות, טקסט הקדמה או פורמט Markdown (כמו ```html). החזר אך ורק את הפסקאות.
    """
    response = model.generate_content(prompt)
    new_insights = response.text.strip()
    new_insights = new_insights.replace("```html", "").replace("```", "").strip()

# 5. עדכון קובץ ה-HTML
with open('index.html', 'r', encoding='utf-8') as f:
    html_content = f.read()

pattern = r'(<div class="insights-content">).*?(</div>)'
updated_html = re.sub(pattern, rf'\1\n{new_insights}\n\2', html_content, flags=re.DOTALL)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(updated_html)

print("Insights script finished successfully!")
