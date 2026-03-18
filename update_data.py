# -*- coding: utf-8 -*-
import os
import re
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from collections import defaultdict
import logging

# הגדרת לוגינג בסיסי
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# מילון עזר לאולמות וקישורי ניווט
ARENA_WAZE_LINKS = {
    "אולם ספורט רמת אלון חיפה": "https://waze.com/ul?q=אולם+ספורט+רמת+אלון+חיפה&navigate=yes",
    "אולם ברזילי רחובות": "https://waze.com/ul?q=אולם+ברזילי+רחובות&navigate=yes",
    "אולם ספורט עין שרה נהריה": "https://waze.com/ul?q=אולם+ספורט+עין+שרה+נהריה&navigate=yes",
    "אולם כדורסל כפר יונה": "https://waze.com/ul?q=אולם+כדורסל+כפר+יונה&navigate=yes",
    "היכל הספורט רוממה חיפה": "https://waze.com/ul?q=היכל+הספורט+רוממה+חיפה&navigate=yes",
    # הוסף עוד אולמות לפי הצורך
}

def get_gemini_model():
    """מחבר למודל השפה של ג'מיני ומחזיר אובייקט מודל."""
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logging.error("GEMINI_API_KEY not found in environment variables.")
            return None
        genai.configure(api_key=api_key)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                return genai.GenerativeModel(m.name)
    except Exception as e:
        logging.error(f"Error connecting to Gemini: {e}")
    return None

def update_insights(soup, model):
    """מפיק תובנות סטטיסטיות על הקבוצה ומחזיר אותן כ-HTML."""
    if not model:
        return "<p>ממתין לעדכון נתונים (שירות ניתוח לא זמין)...</p>"
    
    try:
        table = soup.find('table')
        if not table:
            return "<p>לא נמצאה טבלת ליגה בתוכן האתר.</p>"
        
        standings_text = table.get_text(separator=" | ", strip=True)
        if len(standings_text) < 100:
            return "<p>ממתין לעדכון נתונים משרתי איגוד הכדורסל...</p>"

        prompt = f"""
        אתה פרשן סטטיסטי של כדורסל. להלן נתונים גולמיים שנמשכו כרגע מטבלת הליגה הלאומית בישראל:
        {standings_text}

        כתוב 3 פסקאות קצרות ומקצועיות של מסקנות סטטיסטיות על מצבה של קבוצת 'מכבי רחובות'.
        התייחס למאבק על המקום ה-1, ליתרון הביתיות (מקומות 1-4) ולסכנות מול הקבוצות שמתחתיה לקראת הפלייאוף.
        אל תנחש, תתבסס רק על המתמטיקה והמאזנים שמופיעים בטקסט.
        חובה להשתמש בתגיות HTML של <p> ו-<strong> בלבד.
        אל תוסיף כותרות, טקסט הקדמה או פורמט Markdown. החזר אך ורק את הפסקאות.
        """
        response = model.generate_content(prompt)
        new_insights = response.text.strip().replace("```html", "").replace("```", "").strip()
        return new_insights
    except Exception as e:
        logging.error(f"Error generating insights: {e}")
        return "<p>שגיאה בניתוח הנתונים. אנא נסה שוב מאוחר יותר.</p>"


def update_games(soup):
    """מגרד את לוח המשחקים מהאתר ומחזיר אותו כ-HTML."""
    games_container = soup.find('div', class_='league-games')
    if not games_container:
        logging.warning("Games container 'div.league-games' not found in scraped HTML.")
        return ""

    games_by_round = defaultdict(list)
    
    # 1. איסוף וקיבוץ המשחקים לפי מחזור
    game_divs = games_container.find_all('div', class_='game-row')
    logging.info(f"Found {len(game_divs)} game divs in total.")

    for i, game_div in enumerate(game_divs):
        try:
            mahzor = game_div.find('div', class_='game-round-gamecycle').text.strip()
            date = game_div.find('div', class_='game-date').text.strip()
            time = game_div.find('div', class_='game-hour').text.strip()
            home_team = game_div.find('div', class_='home-team').find('div', class_='team-name').text.strip()
            away_team = game_div.find('div', class_='away-team').find('div', 'team-name').text.strip()
            arena = game_div.find('div', class_='game-hall').text.strip()
            
            game_data = {
                'date': date, 'time': time, 'home': home_team, 'away': away_team, 'arena': arena
            }
            games_by_round[mahzor].append(game_data)
            logging.info(f"Processed game {i+1}: Mahzor {mahzor}, {home_team} vs {away_team}")

        except AttributeError as e:
            logging.warning(f"Could not parse game div #{i+1}. It might be a malformed entry. Error: {e}")
            continue

    # 2. בניית ה-HTML
    html = ""
    logging.info(f"Rendering HTML for {len(games_by_round)} rounds.")
    for mahzor, games in sorted(games_by_round.items()):
        featured_games = []
        other_games = []
        
        for game in games:
            home, away = game['home'], game['away']
            is_featured = any(t in home or t in away for t in ["רחובות", "אילת", "נהריה", "הפועל חיפה"])
            if is_featured:
                featured_games.append(game)
            else:
                other_games.append(game)
        
        if not featured_games and other_games:
            featured_games.append(other_games.pop(0))
            
        if not featured_games and not other_games:
            continue

        for i, game in enumerate(featured_games):
            home_highlight = 'rehovot-highlight' if "רחובות" in game['home'] else ''
            away_highlight = 'rehovot-highlight' if "רחובות" in game['away'] else ''
            waze_link = ARENA_WAZE_LINKS.get(game['arena'], "https://waze.com/ul?navigate=yes")
            
            try:
                date_for_cal = '.'.join(reversed(game['date'].split('/')))
            except:
                date_for_cal = game['date'] # Fallback
            
            toggle_btn = ""
            if i == len(featured_games) - 1 and other_games:
                toggle_btn = f'<button class="details-toggle" onclick="toggleDetails(\'d{mahzor}\')">עוד משחקים <i class="fa-solid fa-chevron-down"></i></button>'
            
            html += f'''
        <tr class="game-row">
            <td>{mahzor}</td><td>{game['date']}</td><td>{game['time']}</td><td class="{home_highlight}">{game['home']}</td><td class="{away_highlight}">{game['away']}</td>
            <td>
                <div class="action-btns">
                    <a href="{waze_link}" target="_blank" class="btn waze-btn"><i class="fa-brands fa-waze"></i> Waze</a>
                    <button onclick="addToCalendar('{game['home'].replace("'", "\\'")} נגד {game['away'].replace("'", "\\'")}', '{date_for_cal}', '{game['time']}', '{game['arena'].replace("'", "\\'")}')" class="btn cal-btn"><i class="fa-regular fa-calendar-plus"></i> יומן</button>
                    {toggle_btn}
                </div>
            </td>
        </tr>'''
        
        # בניית שורות המשחקים הנוספים
        for game in other_games:
            html += f'''
        <tr class="details-panel d{mahzor}">
            <td>{mahzor}</td><td>{game['date']}</td><td>{game['time']}</td><td>{game['home']}</td><td>{game['away']}</td><td></td>
        </tr>'''
            
    return html

def main():
    """הפונקציה הראשית שמריצה את תהליך העדכון."""
    logging.info("Starting data update process.")
    
    # 1. משיכת תוכן האתר
    try:
        url = "https://ibasketball.co.il/league/2025-2/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
    except requests.RequestException as e:
        logging.error(f"Failed to fetch website data: {e}")
        return # יציאה אם אין אפשרות למשוך נתונים

    # 2. עדכון התובנות והמשחקים
    gemini_model = get_gemini_model()
    new_insights_html = update_insights(soup, gemini_model)
    new_games_html = update_games(soup)

    # 3. עדכון קובץ ה-HTML
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            html_content = f.read()

        # עדכון תובנות
        insights_pattern = r'(<div class="insights-content">).*?(</div>)'
        html_content = re.sub(insights_pattern, rf'\1\n{new_insights_html}\n\2', html_content, flags=re.DOTALL)
        logging.info("Insights section prepared for update.")

        # עדכון לוח המשחקים
        if new_games_html:
            games_pattern = r'(<tbody id="games-table-body">).*?(</tbody>)'
            html_content = re.sub(games_pattern, rf'\1\n{new_games_html}\n\2', html_content, flags=re.DOTALL)
            logging.info("Games schedule prepared for update.")
        else:
            logging.warning("Games schedule is empty. HTML will not be updated for games.")

        with open('index.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        logging.info("index.html file updated successfully.")

    except IOError as e:
        logging.error(f"Error reading or writing to index.html: {e}")

if __name__ == "__main__":
    main()
