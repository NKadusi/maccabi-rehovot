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
import urllib.parse
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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

HEBREW_WEEKDAYS = {
    "Monday": "שני", "Tuesday": "שלישי", "Wednesday": "רביעי", 
    "Thursday": "חמישי", "Friday": "שישי", "Saturday": "שבת", "Sunday": "ראשון"
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
    """
    מפיק תובנות סטטיסטיות או מציג טבלת דירוג כגיבוי.
    מחזיר HTML עם התוכן המעודכן, או None במקרה של כשל מוחלט.
    """
    standings_text = ""
    standings_df = None
    
    try:
        timestamp = int(datetime.datetime.now().timestamp())
        url = f"https://ibasketball.co.il/league/2025-2/?nocache={timestamp}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        
        tables = pd.read_html(io.BytesIO(r.content))
        for df in tables:
            # Clean column names
            cleaned_columns = [re.sub(r"['\"`׳’´]", "", str(col)).strip() for col in df.columns]
            df.columns = cleaned_columns

            # Check for essential columns after cleaning
            if 'קבוצה' in df.columns and ('נצ' in df.columns or 'נק' in df.columns):
                standings_df = df
                standings_text = df.to_string(index=False)
                logging.info("Successfully fetched and parsed league standings.")
                break
    except Exception as e:
        logging.error(f"Failed to fetch or parse standings from association site: {e}")
        return None # כשל קריטי, אין נתונים להציג

    # אם לא נמצאה טבלת דירוג, החזר None
    if standings_df is None or not standings_text:
        logging.error("No valid standings data found on the page.")
        return None

    # הכנת HTML חלופי של הטבלה למקרה שה-API ייכשל
    fallback_html = "<p><strong>טבלת הליגה העדכנית:</strong></p>" + standings_df.to_html(index=False, classes='table table-striped', border=0)
    
    # נסיון לקבל תובנות מה-API של Gemini
    if not model:
        logging.warning("Gemini model not available. Returning fallback standings table.")
        return fallback_html

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
        response = model.generate_content(prompt, request_options={'timeout': 45})
        new_insights = response.text.strip()
        
        # ניקוי תגיות Markdown אפשריות
        new_insights = re.sub(r'^```[a-zA-Z]*\s*', '', new_insights, flags=re.IGNORECASE)
        new_insights = re.sub(r'\s*```$', '', new_insights).strip()

        # בדיקה אם התשובה מה-API מכילה תוכן ממשי
        if len(new_insights) < 50:
             logging.warning("Gemini response was too short, likely an error. Returning fallback.")
             return fallback_html

        logging.info("Successfully generated AI insights.")
        return new_insights
    except Exception as e:
        logging.error(f"Error generating insights with Gemini: {e}. Returning fallback standings table.")
        return fallback_html


def update_games(excel_url):
    """קורא את לוח המשחקים, ממיין לפי תאריך, ומקבץ משחקי עבר."""
    logging.info(f"Fetching games from Excel: {excel_url}")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(excel_url, headers=headers, timeout=20)
        response.raise_for_status()
        df_raw = pd.read_excel(io.BytesIO(response.content), header=None, engine='openpyxl')
    except Exception as e:
        logging.error(f"Failed to fetch or parse Excel data: {e}")
        return ""

    header_idx = -1
    for idx, row in df_raw.head(20).iterrows():
        row_str = ' '.join([str(x) for x in row.values if pd.notna(x)])
        if 'מחזור' in row_str and 'תאריך' in row_str:
            header_idx = idx
            break
    
    if header_idx == -1:
        logging.error("Could not find header row in Excel.")
        return ""
        
    df = df_raw.iloc[header_idx + 1:].copy()
    df.columns = df_raw.iloc[header_idx]
    
    cols = list(df.columns)
    def find_col(keywords):
        keywords_lower = [k.lower().strip() for k in keywords]
        for c in cols:
            if isinstance(c, str):
                c_clean = re.sub(r"['\"`׳’´]", "", str(c)).strip().lower()
                c_clean = re.sub(r'\s+', ' ', c_clean)
                if any(k in c_clean for k in keywords_lower):
                    return c
        return None

    mahzor_col = find_col(['מחזור', 'round', 'cycle'])
    date_col = find_col(['תאריך', 'date'])
    time_col = find_col(['שעה', 'time'])
    home_col = find_col(['מארחת', 'קבוצה א', 'home', 'קבוצהא'])
    away_col = find_col(['אורחת', 'קבוצה ב', 'away', 'קבוצהב'])
    arena_col = find_col(['אולם', 'מגרש', 'venue', 'arena'])
    home_score_col = find_col(['home score', 'תוצאה קבוצה א', 'תוצאת מארחת', 'תוצאה א', 'נקודות קבוצה א', 'נקודות בית'])
    away_score_col = find_col(['away score', 'תוצאה קבוצה ב', 'תוצאת אורחת', 'תוצאה ב', 'נקודות קבוצה ב', 'נקודות חוץ'])

    all_games = []
    for index, row in df.iterrows():
        try:
            mahzor = str(row[mahzor_col]).strip()
            if mahzor.endswith('.0'): mahzor = mahzor[:-2]

            raw_date = row[date_col]
            if pd.isna(raw_date): continue

            date_obj = pd.to_datetime(raw_date, dayfirst=True, errors='coerce').to_pydatetime()
            if pd.isna(date_obj): continue

            time_str = "00:00"
            if time_col and pd.notna(row[time_col]):
                time_val = row[time_col]
                if isinstance(time_val, datetime.time):
                    time_str = time_val.strftime('%H:%M')
                else:
                    time_str = str(time_val).strip()[:5]

            home_score = str(row[home_score_col]).strip() if home_score_col and pd.notna(row[home_score_col]) else "-"
            if home_score.endswith('.0'): home_score = home_score[:-2]
            
            away_score = str(row[away_score_col]).strip() if away_score_col and pd.notna(row[away_score_col]) else "-"
            if away_score.endswith('.0'): away_score = away_score[:-2]

            all_games.append({
                'mahzor': mahzor, 'date_obj': date_obj, 'time': time_str,
                'home': str(row[home_col]), 'away': str(row[away_col]), 'arena': str(row.get(arena_col, '')),
                'home_score': home_score if home_score not in ['nan', ''] else '-',
                'away_score': away_score if away_score not in ['nan', ''] else '-'
            })
        except (KeyError, ValueError, TypeError) as e:
            logging.warning(f"Skipping row {index} due to parsing error: {e}")
            continue

    rehovot_games = sorted([g for g in all_games if 'רחובות' in g['home'] or 'רחובות' in g['away']], key=lambda x: x['date_obj'])
    
    other_games_by_round = defaultdict(list)
    top_teams_keywords = ["נהריה", "הפועל חיפה"]
    for g in all_games:
        is_rehovot_game = 'רחובות' in g['home'] or 'רחובות' in g['away']
        is_top_game = any(t in g['home'] or t in g['away'] for t in top_teams_keywords)
        if not is_rehovot_game and is_top_game:
            other_games_by_round[g['mahzor']].append(g)

    past_html, future_html = "", ""
    today = datetime.datetime.now()

    for main_game in rehovot_games:
        is_past = main_game['date_obj'] < today
        row_class = "game-row"
        details_row_class = "details-panel"
        if is_past:
            row_class += " past-game"
            details_row_class += " past-game-details"

        date_str = main_game['date_obj'].strftime('%d.%m.%Y')
        day_he = HEBREW_WEEKDAYS.get(main_game['date_obj'].strftime('%A'), "")
        date_display = f"{day_he}, {date_str} - {main_game['time']}"

        home_hi = 'rehovot-highlight' if 'רחובות' in main_game['home'] else ''
        away_hi = 'rehovot-highlight' if 'רחובות' in main_game['away'] else ''
        
        main_arena_safe = urllib.parse.quote_plus(main_game['arena'])
        main_waze_link = f"https://waze.com/ul?q={main_arena_safe}&navigate=yes"
        main_date_cal = main_game['date_obj'].strftime('%Y.%m.%d')

        main_home_esc, main_away_esc, main_arena_esc = [s.replace("'", "\\'").replace('"', '&quot;') for s in [main_game['home'], main_game['away'], main_game['arena']]]

        top_games = other_games_by_round.get(main_game['mahzor'], [])
        toggle_btn = f'<button class="details-toggle" onclick="toggleDetails(\'d{main_game["mahzor"]}\')">עוד <i class="fa-solid fa-chevron-down"></i></button>' if top_games else ""
        waze_btn = f'<a href="{main_waze_link}" target="_blank" class="btn waze-btn"><i class="fa-brands fa-waze"></i></a>'
        cal_btn = f'<button onclick="addToCalendar(\'{main_home_esc} נגד {main_away_esc}\', \'{main_date_cal}\', \'{main_game["time"]}\', \'{main_arena_esc}\')" class="btn cal-btn"><i class="fa-regular fa-calendar-plus"></i></button>'
        
        current_game_html = f'''<tr class="{row_class}">
            <td>{main_game['mahzor']}</td><td>{date_display}</td><td class="{home_hi}">{main_game['home']}</td>
            <td class="game-result">{main_game["home_score"]}</td><td class="game-result">{main_game["away_score"]}</td>
            <td class="{away_hi}">{main_game['away']}</td><td class="action-col">{waze_btn}</td>
            <td class="action-col">{cal_btn}</td><td class="action-col">{toggle_btn}</td></tr>'''

        for game in top_games:
            date_cal_top = game['date_obj'].strftime('%Y.%m.%d')
            day_he_top = HEBREW_WEEKDAYS.get(game['date_obj'].strftime('%A'), "")
            date_display_top = f"{day_he_top}, {game['date_obj'].strftime('%d.%m.%Y')} - {game['time']}"
            
            game_arena_safe = urllib.parse.quote_plus(game['arena'])
            waze_link_top = f"https://waze.com/ul?q={game_arena_safe}&navigate=yes"
            game_home_esc, game_away_esc, game_arena_esc = [s.replace("'", "\\'").replace('"', '&quot;') for s in [game['home'], game['away'], game['arena']]]
            
            waze_btn_top = f'<a href="{waze_link_top}" target="_blank" class="btn waze-btn"><i class="fa-brands fa-waze"></i></a>'
            cal_btn_top = f'<button onclick="addToCalendar(\'{game_home_esc} נגד {game_away_esc}\', \'{date_cal_top}\', \'{game["time"]}\', \'{game_arena_esc}\')" class="btn cal-btn"><i class="fa-regular fa-calendar-plus"></i></button>'
            
            # Add the mahzor-specific class `d{mahzor}` for toggleDetails
            current_game_html += f'''<tr class="{details_row_class} d{game['mahzor']}">
                <td>{game['mahzor']}</td><td>{date_display_top}</td><td>{game['home']}</td>
                <td class="game-result">{game["home_score"]}</td><td class="game-result">{game["away_score"]}</td>
                <td>{game['away']}</td><td class="action-col">{waze_btn_top}</td>
                <td class="action-col">{cal_btn_top}</td><td class="action-col"></td></tr>'''
        
        if is_past:
            past_html += current_game_html
        else:
            future_html += current_game_html
            
    final_html = future_html
    if past_html:
        toggle_row = f'''<tr class="game-row" id="past-games-toggle-row">
            <td colspan="9" style="text-align: center; cursor: pointer;" onclick="togglePastGames()">
                <button id="past-games-toggle-btn" class="details-toggle">הצג משחקים קודמים</button>
            </td>
        </tr>'''
        final_html = toggle_row + past_html + future_html
        
    return final_html

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
            
        # ניקוי אוטומטי של שורות ישנות (כולל "שורות רפאים" שהשתכפלו מחוץ לטבלה)
        cleanup_pattern = r'(<tbody id="games-table-body">).*?(</table>)'
        html_content = re.sub(cleanup_pattern, r'\1\n</tbody>\n        \2', html_content, flags=re.DOTALL)

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
            html_content = re.sub(insights_pattern, lambda m: f"{m.group(1)}\n{new_insights_html}\n{m.group(2)}", html_content, flags=re.DOTALL)
            logging.info("Insights section prepared for update.")
        else:
            logging.warning("Insights update skipped due to missing data or error.")

        # עדכון לוח המשחקים
        if new_games_html:
            games_pattern = r'(<tbody id="games-table-body">).*?(</tbody>)'
            html_content = re.sub(games_pattern, lambda m: f"{m.group(1)}\n{new_games_html}\n{m.group(2)}", html_content, flags=re.DOTALL)
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
