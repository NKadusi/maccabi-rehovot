import os
import re
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

# 1. התחברות לבינה המלאכותית
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

# 2. משיכת הנתונים מהקישור החדש של איגוד הכדורסל
try:
    url = "https://ibasketball.co.il/league/2025-2/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # חיפוש הטבלה בתוך הדף
    tables = soup.find_all('table')
    if tables:
        standings_text = tables[0].get_text(separator=" | ", strip=True)
    else:
        standings_text = "ERROR: Table not found in HTML"

except Exception as e:
    standings_text = f"ERROR: {e}"
    print(f"FAILED TO FETCH DATA: {e}")

# 3. מנגנון הגנה
if "ERROR" in standings_text or len(standings_text) < 100:
    new_insights = "<p>ממתין לעדכון נתונים משרתי איגוד הכדורסל...</p>"
    print("Could not get valid table data. Falling back to waiting message.")
else:
    # 4. בקשת המסקנות
    prompt = f"""
    אתה פרשן סטטיסטי של כדורסל. להלן נתונים גולמיים שנמשכו כרגע מטבלת הליגה הלאומית בישראל:
    {standings_text}

    כתוב 3 פסקאות קצרות ומקצועיות של מסקנות סטטיסטיות על מצבה של קבוצת 'מכבי רחובות'.
    התייחס למאבק על המקום ה-1, ליתרון הביתיות (מקומות 1-4) ולסכנות מול הקבוצות שמתחתיה לקראת הפלייאוף.
    אל תנחש, תתבסס רק על המתמטיקה והמאזנים שמופיעים בטקסט.
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
