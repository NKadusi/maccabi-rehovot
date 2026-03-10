import os
import re
import requests
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

# 2. משיכת נתונים ישירות מהשרתים של SofaScore (ללא חסימות HTML)
try:
    # מזהה הטורניר והעונה של הליגה הלאומית 25/26 מתוך הווידג'ט שלך
    url = "https://api.sofascore.com/api/v1/unique-tournament/40315/season/83414/standings/total"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    response = requests.get(url, headers=headers, timeout=10)
    data = response.json()
    
    standings_text = "טבלת הליגה הלאומית:\n"
    # מעבר על קבוצות הטופ 10 כדי לחסוך באסימוני קריאה ל-AI
    for row in data['standings'][0]['rows'][:10]:
        pos = row['position']
        team = row['team']['name']
        matches = row['matches']
        wins = row['wins']
        losses = row['losses']
        standings_text += f"מקום {pos}: {team} | משחקים: {matches} | מאזן: {wins}-{losses}\n"

except Exception as e:
    standings_text = "ERROR"
    print(f"Error fetching data: {e}")

# 3. מנגנון הגנה
if standings_text == "ERROR" or len(standings_text) < 50:
    new_insights = "<p>ממתין לעדכון נתונים משרתי התוצאות...</p>"
else:
    # 4. בקשת המסקנות
    prompt = f"""
    אתה פרשן סטטיסטי של כדורסל. להלן נתונים גולמיים שנמשכו כרגע מטבלת הליגה הלאומית בישראל:
    {standings_text}

    כתוב 3 פסקאות קצרות ומקצועיות של מסקנות סטטיסטיות על מצבה של קבוצת 'מכבי רחובות' (Maccabi Rehovot).
    התייחס למאבק על המקום ה-1, ליתרון הביתיות (מקומות 1-4) ולסכנות מול הקבוצות שמתחתיה.
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
