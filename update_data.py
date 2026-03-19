# -*- coding: utf-8 -*-
import os
import re
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from collections import defaultdict
import logging
import pandas as pd
import io
import datetime

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

def update_insights(model):
    """מפיק תובנות סטטיסטיות על הקבוצה ומחזיר אותן כ-HTML."""
    if not model:
        return None
    
    standings_text = ""
    # משיכת טבלת הדירוג הרשמית מאתר איגוד הכדורסל 
    # עקיפת זיכרון מטמון (Cache) כדי לקבל נתונים טריים כמו באקסל
    try:
        timestamp = int(datetime.datetime.now().timestamp())
        url = f"https://ibasketball.co.il/league/2025-2/?nocache={timestamp}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            tables = pd.read_html(io.BytesIO(r.content))
            for df in tables:
                text_rep = df.to_string()
                if 'קבוצה' in text_rep and ('נצחונות' in text_rep or 'נקודות' in text_rep):
                    standings_text = df.to_string(index=False)
                    break
    except Exception as e:
        logging.warning(f"Failed to fetch standings from association site: {e}")

    if not standings_text:
        logging.error("No standings data found.")
        return None # מחזיר None כדי לא לדרוס את הקיים במקרה של שגיאה

    try:
        prompt = f"""
        אתה פרשן סטטיסטי של כדורסל. להלן נתונים גולמיים ומעודכנים מהטבלה הרשמית של איגוד הכדורסל בישראל:
        {standings_text}

        כתוב 3 פסקאות קצרות ומקצועיות של מסקנות סטטיסטיות על מצבה של קבוצת 'מכבי רחובות' (או מכבי ברק רחובות).
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
        return None


def update_games(excel_url):
    """קורא את לוח המשחקים ישירות מקובץ האקסל הרשמי ומחזיר אותו כ-HTML."""
    logging.info(f"Fetching games from Excel: {excel_url}")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(excel_url, headers=headers, timeout=20)
        response.raise_for_status()
            
        # ניסיון קריאה ללא כותרות כדי למצוא את השורה האמיתית
        try:
            df_raw = pd.read_excel(io.BytesIO(response.content), header=None, engine='openpyxl')
        except Exception as e:
            logging.warning(f"Could not read as Excel with openpyxl, trying HTML fallback. Error: {e}")
            try:
                html_content = response.content.decode('utf-8', errors='ignore')
                df_raw = pd.read_html(io.StringIO(html_content), header=None)[0]
            except Exception as ex:
                logging.error(f"HTML fallback failed: {ex}")
                return ""
                
        header_idx = -1
        for idx, row in df_raw.head(20).iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)])
            if 'מחזור' in row_str and ('תאריך' in row_str or 'מארחת' in row_str or 'קבוצה' in row_str):
                header_idx = idx
                break
                
        if header_idx == -1:
            logging.error("Could not find header row in Excel.")
            return ""
            
        df = df_raw.iloc[header_idx + 1:].copy()
        df.columns = df_raw.iloc[header_idx]
            
    except Exception as e:
        logging.error(f"Failed to fetch or parse Excel data: {e}")
        return ""

    cols = list(df.columns)
    def find_col(keywords):
        for c in cols:
            if isinstance(c, str):
                c_clean = str(c).replace('"', '').replace("'", "").strip()
                if any(k in c_clean for k in keywords):
                    return c
        return None
        
    mahzor_col = find_col(['מחזור', 'Round', 'Cycle'])
    date_col = find_col(['תאריך', 'Date'])
    time_col = find_col(['שעה', 'Time'])
    home_col = find_col(['מארחת', 'קבוצה א', 'Home', 'קבוצהא'])
    away_col = find_col(['אורחת', 'קבוצה ב', 'Away', 'קבוצהב'])
    arena_col = find_col(['אולם', 'מגרש', 'Venue', 'Arena'])

    games_by_round = defaultdict(list)
    
    if not (mahzor_col and date_col and home_col and away_col):
        logging.error(f"Missing essential columns. Found headers: {cols}")
        return ""

    for index, row in df.iterrows():
        mahzor = str(row[mahzor_col]).strip()
        if mahzor == 'nan' or not mahzor: continue
        if mahzor.endswith('.0'): mahzor = mahzor[:-2]
            
        raw_date = row[date_col]
        if pd.isna(raw_date): continue
            
        if isinstance(raw_date, datetime.datetime):
            date_str = raw_date.strftime('%d.%m')
        else:
            date_str = str(raw_date).strip()
            if '/' in date_str:
                parts = date_str.split('/')
                if len(parts) >= 2: date_str = f"{parts[0].zfill(2)}.{parts[1].zfill(2)}"
            elif '-' in date_str:
                parts = date_str.split('-')
                if len(parts) >= 3: date_str = f"{parts[2].zfill(2)}.{parts[1].zfill(2)}"
            
        raw_time = row[time_col] if time_col else ''
        if pd.isna(raw_time): time_str = "00:00"
        elif isinstance(raw_time, datetime.time): time_str = raw_time.strftime('%H:%M')
        else: time_str = str(raw_time).strip()[:5]

        home = str(row[home_col]).strip() if not pd.isna(row[home_col]) else ''
        away = str(row[away_col]).strip() if not pd.isna(row[away_col]) else ''
        arena = str(row[arena_col]).strip() if arena_col and not pd.isna(row[arena_col]) else ''

        if not home or not away or home == 'nan' or away == 'nan': continue

        games_by_round[mahzor].append({'date': date_str, 'time': time_str, 'home': home, 'away': away, 'arena': arena})

    html = ""
    logging.info(f"Rendering HTML for {len(games_by_round)} rounds.")
    top_teams_keywords = ["אילת", "נהריה", "הפועל חיפה"]
    
    def sort_key(k):
        try: return int(re.search(r'\d+', k).group())
        except: return 999

    for mahzor, games in sorted(games_by_round.items(), key=lambda item: sort_key(item[0])):
        rehovot_game = None
        top_games = []
        
        for game in games:
            if "רחובות" in game['home'] or "רחובות" in game['away']:
                rehovot_game = game
            elif any(t in game['home'] or t in game['away'] for t in top_teams_keywords):
                top_games.append(game)
        
        if not rehovot_game and not top_games:
            continue

        main_game = rehovot_game if rehovot_game else top_games.pop(0)
        home_hi = 'rehovot-highlight' if 'רחובות' in main_game['home'] else ''
        away_hi = 'rehovot-highlight' if 'רחובות' in main_game['away'] else ''
        main_waze = ARENA_WAZE_LINKS.get(main_game['arena'], "https://waze.com/ul?navigate=yes")
            
        try:
            main_date_cal = '.'.join(reversed(main_game['date'].split('.')))
        except:
            main_date_cal = main_game['date']
            
        toggle_btn = ""
        if top_games:
            toggle_btn = f'<button class="details-toggle" onclick="toggleDetails(\'d{mahzor}\')">עוד משחקים <i class="fa-solid fa-chevron-down"></i></button>'
            
        main_home_esc = main_game['home'].replace("'", "\\'")
        main_away_esc = main_game['away'].replace("'", "\\'")
        main_arena_esc = main_game['arena'].replace("'", "\\'")
        
        html += f'''
        <tr class="game-row">
            <td>{mahzor}</td><td>{main_game['date']}</td><td>{main_game['time']}</td><td class="{home_hi}">{main_game['home']}</td><td class="{away_hi}">{main_game['away']}</td>
            <td>
                <div class="action-btns">
                    <a href="{main_waze}" target="_blank" class="btn waze-btn"><i class="fa-brands fa-waze"></i> Waze</a>
                    <button onclick="addToCalendar('{main_home_esc} נגד {main_away_esc}', '{main_date_cal}', '{main_game['time']}', '{main_arena_esc}')" class="btn cal-btn"><i class="fa-regular fa-calendar-plus"></i> יומן</button>
                    {toggle_btn}
                </div>
            </td>
        </tr>'''
        
        for game in top_games:
            try:
                date_cal = '.'.join(reversed(game['date'].split('.')))
            except:
                date_cal = game['date']
            waze_link = ARENA_WAZE_LINKS.get(game['arena'], "https://waze.com/ul?navigate=yes")
            game_home_esc = game['home'].replace("'", "\\'")
            game_away_esc = game['away'].replace("'", "\\'")
            game_arena_esc = game['arena'].replace("'", "\\'")
            html += f'''
        <tr class="details-panel d{mahzor}">
            <td>{mahzor}</td><td>{game['date']}</td><td>{game['time']}</td><td>{game['home']}</td><td>{game['away']}</td>
            <td>
                <div class="action-btns">
                    <a href="{waze_link}" target="_blank" class="btn waze-btn"><i class="fa-brands fa-waze"></i> Waze</a>
                    <button onclick="addToCalendar('{game_home_esc} נגד {game_away_esc}', '{date_cal}', '{game['time']}', '{game_arena_esc}')" class="btn cal-btn"><i class="fa-regular fa-calendar-plus"></i> יומן</button>
                </div>
            </td>
        </tr>'''
            
    return html

def main():
    """הפונקציה הראשית שמריצה את תהליך העדכון."""
    logging.info("Starting data update process.")
    
    # עדכון התובנות מהטבלה הרשמית והמשחקים מקובץ האקסל
    gemini_model = get_gemini_model()
    new_insights_html = update_insights(gemini_model)
    
    excel_url = "https://ibasketball.co.il/league/2025-2/?feed=xlsx&league_id=119474"
    new_games_html = update_games(excel_url)

    # 3. עדכון קובץ ה-HTML
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
            
        # בדיקה האם יש שינויים בלוח המשחקים (משחקים חדשים או שינוי זמנים)
        if new_games_html:
            check_pattern = r'(<tbody id="games-table-body">)(.*?)(</tbody>)'
            old_match = re.search(check_pattern, html_content, flags=re.DOTALL)
            if old_match:
                old_html = old_match.group(2).strip()
                if old_html != new_games_html.strip():
                    logging.info("🚨 התראה: זוהו משחקים חדשים או שינויים בלוח המשחקים!")
                    step_summary = os.environ.get('GITHUB_STEP_SUMMARY')
                    if step_summary:
                        with open(step_summary, 'a', encoding='utf-8') as sf:
                            sf.write("### 🚨 לוח המשחקים עודכן!\nהסקריפט מצא משחקים חדשים או עדכוני שעות/תאריכים בקובץ האקסל ועדכן את האתר בהתאם.\n")
                else:
                    logging.info("לוח המשחקים נשאר ללא שינוי.")

        if new_insights_html:
            insights_pattern = r'(<div class="insights-content">).*?(</div>)'
            html_content = re.sub(insights_pattern, rf'\1\n{new_insights_html}\n\2', html_content, flags=re.DOTALL)
            logging.info("Insights section prepared for update.")
        else:
            logging.warning("Insights update skipped due to missing data or error.")

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
