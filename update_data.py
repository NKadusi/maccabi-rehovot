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
        new_insights = response.text.strip()
        new_insights = re.sub(r'^```[a-zA-Z]*\s*', '', new_insights, flags=re.IGNORECASE)
        new_insights = re.sub(r'\s*```$', '', new_insights).strip()
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
        keywords_lower = [k.lower().strip() for k in keywords]
        for c in cols:
            if isinstance(c, str):
                c_clean = str(c).replace('"', '').replace("'", "").strip().lower()
                c_clean = re.sub(r'\s+', ' ', c_clean) # מנקה רווחים כפולים
                if any(k in c_clean for k in keywords_lower):
                    return c
        return None
        
    mahzor_col = find_col(['מחזור', 'Round', 'Cycle'])
    date_col = find_col(['תאריך', 'Date'])
    time_col = find_col(['שעה', 'Time'])
    home_col = find_col(['מארחת', 'קבוצה א', 'Home', 'קבוצהא'])
    away_col = find_col(['אורחת', 'קבוצה ב', 'Away', 'קבוצהב'])
    arena_col = find_col(['אולם', 'מגרש', 'Venue', 'Arena'])
    
    # איתור עמודות התוצאות הספציפיות למארחת ולאורחת
    home_score_col = find_col(['Home Score', 'Home score', 'HOME SCORE', 'תוצאה קבוצה א', 'תוצאת מארחת'])
    away_score_col = find_col(['Away Score', 'Away score', 'AWAY SCORE', 'תוצאה קבוצה ב', 'תוצאת אורחת'])

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
            date_obj = raw_date
        else:
            try:
                date_obj = pd.to_datetime(raw_date, dayfirst=True, errors='coerce')
                if pd.isna(date_obj):
                    date_obj = pd.to_datetime(raw_date, errors='coerce')
            except Exception:
                date_obj = None

        if pd.isna(date_obj):
            date_str = str(raw_date).strip()
            day_he = ""
        else:
            date_str = date_obj.strftime('%d.%m.%Y')
            day_en = date_obj.strftime('%A')
            day_he = HEBREW_WEEKDAYS.get(day_en, "")

        raw_time = row[time_col] if time_col else ''
        if pd.isna(raw_time): time_str = "00:00"
        elif isinstance(raw_time, datetime.time): time_str = raw_time.strftime('%H:%M')
        else: time_str = str(raw_time).strip()[:5]

        home = str(row[home_col]).strip() if not pd.isna(row[home_col]) else ''
        away = str(row[away_col]).strip() if not pd.isna(row[away_col]) else ''
        arena = str(row[arena_col]).strip() if arena_col and not pd.isna(row[arena_col]) else ''
        
        home_score, away_score = "", ""
        if home_score_col:
            hs = str(row[home_score_col]).strip()
            if hs and hs.lower() not in ['nan', 'none', '-', 'null', '']:
                if hs.endswith('.0'): hs = hs[:-2]
                home_score = hs
        if away_score_col:
            aws = str(row[away_score_col]).strip()
            if aws and aws.lower() not in ['nan', 'none', '-', 'null', '']:
                if aws.endswith('.0'): aws = aws[:-2]
                away_score = aws

        if not home or not away or home == 'nan' or away == 'nan': continue

        games_by_round[mahzor].append({'date': date_str, 'day': day_he, 'time': time_str, 'home': home, 'away': away, 'arena': arena, 'home_score': home_score, 'away_score': away_score})

    html = ""
    logging.info(f"Rendering HTML for {len(games_by_round)} rounds.")
    top_teams_keywords = ["נהריה", "הפועל חיפה"]
    
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
        
        # Per user request, only show rounds where Maccabi Rehovot plays
        if not rehovot_game:
            continue

        main_game = rehovot_game
        home_hi = 'rehovot-highlight' if 'רחובות' in main_game['home'] else ''
        away_hi = 'rehovot-highlight' if 'רחובות' in main_game['away'] else ''
        
        # New combined date format
        date_display = f"{main_game['day']}, {main_game['date']} - {main_game['time']}"

        main_arena_safe = urllib.parse.quote_plus(main_game['arena']) if main_game['arena'] else ""
        main_waze_link = ARENA_WAZE_LINKS.get(main_game['arena'], f"https://waze.com/ul?q={main_arena_safe}&navigate=yes" if main_arena_safe else "https://waze.com/ul?navigate=yes")
            
        try:
            main_date_cal = '.'.join(reversed(main_game['date'].split('.')))
        except:
            main_date_cal = main_game['date']
            
        main_home_esc = main_game['home'].replace("'", "\\'").replace('"', '&quot;')
        main_away_esc = main_game['away'].replace("'", "\\'").replace('"', '&quot;')
        main_arena_esc = main_game['arena'].replace("'", "\\'").replace('"', '&quot;')

        home_score_val = main_game["home_score"] if main_game.get('home_score') else '-'
        away_score_val = main_game["away_score"] if main_game.get('away_score') else '-'
        
        waze_btn = f'<a href="{main_waze_link}" target="_blank" class="btn waze-btn"><i class="fa-brands fa-waze"></i> ניווט</a>'
        cal_btn = f'<button onclick="addToCalendar(\'{main_home_esc} נגד {main_away_esc}\', \'{main_date_cal}\', \'{main_game["time"]}\', \'{main_arena_esc}\')" class="btn cal-btn"><i class="fa-regular fa-calendar-plus"></i> ליומן</button>'
        
        toggle_btn = ""
        if top_games:
            toggle_btn = f'<button class="details-toggle" onclick="toggleDetails(\'d{mahzor}\')">עוד משחקים <i class="fa-solid fa-chevron-down"></i></button>'
        
        html += f'''
        <tr class="game-row">
            <td>{mahzor}</td>
            <td>{date_display}</td>
            <td class="{home_hi}">{main_game['home']}</td>
            <td class="game-result">{home_score_val}</td>
            <td class="game-result">{away_score_val}</td>
            <td class="{away_hi}">{main_game['away']}</td>
            <td class="action-col">{waze_btn}</td>
            <td class="action-col">{cal_btn}</td>
            <td class="action-col">{toggle_btn}</td>
        </tr>'''
        
        for game in top_games:
            try:
                date_cal = '.'.join(reversed(game['date'].split('.')))
            except:
                date_cal = game['date']
            
            date_display_top = f"{game['day']}, {game['date']} - {game['time']}"

            game_arena_safe = urllib.parse.quote_plus(game['arena']) if game['arena'] else ""
            waze_link = ARENA_WAZE_LINKS.get(game['arena'], f"https://waze.com/ul?q={game_arena_safe}&navigate=yes" if game_arena_safe else "https://waze.com/ul?navigate=yes")
            game_home_esc = game['home'].replace("'", "\\'").replace('"', '&quot;')
            game_away_esc = game['away'].replace("'", "\\'").replace('"', '&quot;')
            game_arena_esc = game['arena'].replace("'", "\\'").replace('"', '&quot;')

            home_score_val_top = game["home_score"] if game.get('home_score') else '-'
            away_score_val_top = game["away_score"] if game.get('away_score') else '-'

            waze_btn_top = f'<a href="{waze_link}" target="_blank" class="btn waze-btn"><i class="fa-brands fa-waze"></i> ניווט</a>'
            cal_btn_top = f'<button onclick="addToCalendar(\'{game_home_esc} נגד {game_away_esc}\', \'{date_cal}\', \'{game["time"]}\', \'{game_arena_esc}\')" class="btn cal-btn"><i class="fa-regular fa-calendar-plus"></i> ליומן</button>'

            html += f'''
        <tr class="details-panel d{mahzor}">
            <td>{mahzor}</td>
            <td>{date_display_top}</td>
            <td>{game['home']}</td>
            <td class="game-result">{home_score_val_top}</td>
            <td class="game-result">{away_score_val_top}</td>
            <td>{game['away']}</td>
            <td class="action-col">{waze_btn_top}</td>
            <td class="action-col">{cal_btn_top}</td>
            <td class="action-col"></td>
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
