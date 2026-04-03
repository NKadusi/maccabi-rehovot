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
from datetime import datetime, timedelta, time
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
    """מגדיר את החיבור ל-Gemini ומחזיר מודל."""
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logging.error("GEMINI_API_KEY not found in environment variables.")
            return None
        genai.configure(api_key=api_key)
        # שימוש במודל העדכני והמהיר של ג'מיני
        model = genai.GenerativeModel('gemini-1.5-flash')
        return model
    except Exception as e:
        logging.error(f"Error connecting to Gemini: {e}")
    return None

def update_insights(model, games_list):
    """מפיק תובנות סטטיסטיות על הקבוצה ומחזיר אותן כ-HTML."""
    if not model or not games_list:
        return None
    
    standings_text = ""
    # משיכת טבלת הדירוג הרשמית מאתר איגוד הכדורסל 
    # עקיפת זיכרון מטמון (Cache) כדי לקבל נתונים טריים כמו באקסל
    try:
        timestamp = int(datetime.now().timestamp())
        url = f"https://ibasketball.co.il/league/2025-2/?league_id=119474&nocache={timestamp}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            tables = pd.read_html(io.BytesIO(r.content))
            for df in tables:
                text_rep = df.to_string()
                if 'קבוצה' in text_rep and any(k in text_rep for k in ['ניצחונות', 'נקודות', 'נק\'', 'משחקים']):
                    standings_text = df.to_string(index=False)
                    break
    except Exception as e:
        logging.warning(f"Failed to fetch standings from association site: {e}")

    # אם לא נמצאה טבלה, נבנה טקסט בסיסי מרשימת המשחקים כגיבוי
    if not standings_text:
        logging.warning("No standings table found, using game list as primary source.")
        standings_text = "Official table unavailable. Use game results for calculations."
    else:
        logging.info(f"Standings data fetched. Length: {len(standings_text)} chars.")

    # אם standings_text זמין, ננסה להסיר את השורה של מכבי רחובות כדי למנוע נתונים סותרים
    filtered_standings_text = standings_text
    if standings_text and ("מכבי רחובות" in standings_text or "Maccabi Rehovot" in standings_text):
        lines = standings_text.split('\n')
        filtered_lines = [line for line in lines if "מכבי רחובות" not in line and "Maccabi Rehovot" not in line]
        filtered_standings_text = "\n".join(filtered_lines)
        logging.info("Removed Maccabi Rehovot's row from official standings to prevent data conflict.")
    # חישוב מאזן מדויק עבור רחובות ישירות מהאקסל (Live Stats)
    rehovot_wins = 0
    rehovot_losses = 0
    rehovot_gp = 0
    for g in games_list:
        if 'רחובות' in g['home'] or 'רחובות' in g['away']:
            if g['home_score'] != '-' and g['away_score'] != '-':
                rehovot_gp += 1
                try:
                    h_score = int(g['home_score'])
                    a_score = int(g['away_score'])
                    if 'רחובות' in g['home']:
                        if h_score > a_score: rehovot_wins += 1
                        else: rehovot_losses += 1
                    else:
                        if a_score > h_score: rehovot_wins += 1
                        else: rehovot_losses += 1
                except: continue
    
    rehovot_points = (rehovot_wins * 2) + rehovot_losses
    live_stats_msg = f"מכבי רחובות: {rehovot_gp} משחקים, {rehovot_wins} ניצחונות, {rehovot_losses} הפסדים, {rehovot_points} נקודות."

    # יצירת סיכום של תוצאות מהאקסל כדי לעזור למודל לעדכן את הנתונים
    results_summary = "\n".join([
        f"מחזור {g['mahzor']}: {g['home']} {g['home_score']} - {g['away_score']} {g['away']}"
        for g in games_list if (g['home_score'] != '-' and g['away_score'] != '-') and ('רחובות' in g['home'] or 'רחובות' in g['away'])
    ])

    try:
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        prompt_he = f"""
        Today's Date: {datetime.now().strftime('%d/%m/%Y')}
        אתה פרשן כדורסל מומחה. להלן נתוני הטבלה הכללית עבור שאר הקבוצות (שיכולה להיות לא מעודכנת):
        {filtered_standings_text}

        נתוני אמת של מכבי רחובות (השתמש רק בהם!):
        {live_stats_msg}

        תוצאות המשחקים האחרונים של רחובות:
        {results_summary}

        משימה: כתוב 3 פסקאות ניתוח על מצבה של מכבי רחובות בטבלה. 
        השתמש במאזן המדויק שסופק לעיל: {rehovot_wins} ניצחונות ו-{rehovot_losses} הפסדים.
        נתח את הסיכויים מול נהריה והפועל חיפה.
        
        דגשים:
        1. אל תוסיף הקדמות. החזר רק פסקאות עטופות ב-<p>. 
        השתמש ב-<strong> להדגשת שמות קבוצות ומספרים. המר כל סימון Markdown של כוכביות לתגיות HTML.
        """

        prompt_en = f"""
        Today's Date: {datetime.now().strftime('%d/%m/%Y')}
        Official Standings Table for other teams (may be outdated):
        {filtered_standings_text}

        Verified Live Stats for Maccabi Rehovot (MUST USE THESE):
        {live_stats_msg}

        Recent Rehovot Results:
        {results_summary}

        Task: Write 3 analytical paragraphs in English. 
        Maccabi Rehovot has exactly {rehovot_points} points from {rehovot_gp} games.
        Analyze the race for 2nd place against Ironi Nahariya and Hapoel Haifa, using Rehovot's updated stats and the standings data for other teams.

        Use ONLY <p> and <strong> tags. Convert all Markdown bold (**) to <strong>.
        Return only the HTML content.
        """

        def process_ai_response(response_text, lang_class):
            if not response_text or len(response_text) < 20: return ""
            # ניקוי פורמט Markdown
            text = re.sub(r'```(?:html|markdown)?\s*', '', response_text, flags=re.IGNORECASE)
            text = text.replace('```', '').strip()
            
            # המרת Markdown Bold ל-HTML Strong וניקוי תגיות מיותרות
            text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
            
            p_matches = re.findall(r'<p\b[^>]*>(.*?)</p>', text, flags=re.IGNORECASE | re.DOTALL)
            paragraphs = [m.strip() for m in p_matches if m.strip()] if p_matches else [p.strip() for p in re.split(r'\n+', text) if p.strip()]
            
            wrapped = ""
            intros = ('here is', 'certainly', 'analysis:', 'sure', 'הנה הניתוח', 'להלן הניתוח', 'בבקשה', 'ניתוח מצבה')
            for p in paragraphs:
                clean_p = re.sub(r'</?p\b[^>]*>', '', p, flags=re.IGNORECASE).strip()
                for intro in intros:
                    if clean_p.lower().startswith(intro):
                        clean_p = re.sub(f'^{intro}:?\\s*', '', clean_p, flags=re.IGNORECASE).strip()
                
                if clean_p:
                    wrapped += f'<p class="{lang_class}">{clean_p}</p>\n'
            return wrapped

        # בדיקה שהתגובה אכן מכילה טקסט לפני הגישה ל-.text
        res_he = model.generate_content(prompt_he, safety_settings=safety_settings)
        new_insights_he = process_ai_response(res_he.text, "lang-he") if (res_he and res_he.candidates) else ""

        res_en = model.generate_content(prompt_en, safety_settings=safety_settings)
        new_insights_en = process_ai_response(res_en.text, "lang-en") if (res_en and res_en.candidates) else ""

        new_insights = f"{new_insights_he}\n{new_insights_en}"
        return new_insights
    except Exception as e:
        logging.error(f"Error generating insights: {e}")
        return None


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
        return "", None, []

    header_idx = -1
    for idx, row in df_raw.head(20).iterrows():
        row_str = ' '.join([str(x) for x in row.values if pd.notna(x)])
        if 'מחזור' in row_str and 'תאריך' in row_str:
            header_idx = idx
            break
    
    if header_idx == -1:
        logging.error("Could not find header row in Excel.")
        return "", None, []
        
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
    home_score_col = find_col(['home score', 'תוצאה קבוצה א', 'תוצאת מארחת', 'תוצאה א', 'נקודות בית'])
    away_score_col = find_col(['away score', 'תוצאה קבוצה ב', 'תוצאת אורחת', 'תוצאה ב', 'נקודות חוץ'])
    general_score_col = find_col(['תוצאה', 'score', 'תוצאה סופית'])

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
                if isinstance(time_val, time):
                    time_str = time_val.strftime('%H:%M')
                else:
                    time_str = str(time_val).strip()[:5]

            try:
                if time_str and time_str != "00:00" and time_str != "-":
                    h, m = map(int, time_str.split(':'))
                    date_obj = date_obj.replace(hour=h, minute=m)
            except Exception:
                pass

            home_score, away_score = "-", "-"
            # ניסיון חילוץ מעמודות נפרדות
            if home_score_col and pd.notna(row[home_score_col]):
                home_score = str(row[home_score_col]).strip()
            if away_score_col and pd.notna(row[away_score_col]):
                away_score = str(row[away_score_col]).strip()

            # אם לא נמצאו תוצאות בנפרד, נבדוק אם יש עמודה מאוחדת (למשל 85-70)
            if (home_score == "-" or away_score == "-") and general_score_col and pd.notna(row[general_score_col]):
                score_val = str(row[general_score_col]).strip()
                parts = re.split(r'[-\s:]+', score_val)
                if len(parts) >= 2:
                    p1 = "".join(filter(str.isdigit, parts[0]))
                    p2 = "".join(filter(str.isdigit, parts[1]))
                    if p1 and p2:
                        home_score, away_score = p1, p2

            # ניקוי סיומות מיותרות ובדיקת תקינות
            home_score = home_score[:-2] if home_score.endswith('.0') else home_score
            away_score = away_score[:-2] if away_score.endswith('.0') else away_score
            
            home_score = home_score if home_score not in ['nan', '', 'None'] else '-'
            away_score = away_score if away_score not in ['nan', '', 'None'] else '-'

            all_games.append({
                'mahzor': mahzor, 'date_obj': date_obj, 'time': time_str,
                'home': str(row[home_col]), 'away': str(row[away_col]), 'arena': str(row.get(arena_col, '')),
                'home_score': home_score, 'away_score': away_score
            })
        except (KeyError, ValueError, TypeError) as e:
            logging.warning(f"Skipping row {index} due to parsing error: {e}")
            continue

    rehovot_games = sorted([g for g in all_games if 'רחובות' in g['home'] or 'רחובות' in g['away']], key=lambda x: x['date_obj'])
    
    # הגדרת 'היום' לפי שעון ישראל (UTC+3) לצורך השוואה נכונה של משחקי עבר/עתיד
    today = datetime.utcnow() + timedelta(hours=3)
    
    other_games_by_round = defaultdict(list)
    top_teams_keywords = ["נהריה", "הפועל חיפה"]
    for g in all_games:
        is_rehovot_game = 'רחובות' in g['home'] or 'רחובות' in g['away']
        is_top_game = any(t in g['home'] or t in g['away'] for t in top_teams_keywords)
        if not is_rehovot_game and is_top_game:
            other_games_by_round[g['mahzor']].append(g)

    # מציאת האינדקס של המשחק האחרון ששוחק (כולל היום)
    past_game_indices = [i for i, g in enumerate(rehovot_games) if g['date_obj'] < today]
    last_played_game_idx = past_game_indices[-1] if past_game_indices else -1

    hidden_past_html = ""
    visible_html = ""

    # מציאת המשחק הבא עבור שעון העצר (המשחק הראשון שזמנו גדול מהנוכחי)
    next_game_date_str = None
    first_future_game = next((g for g in rehovot_games if g['date_obj'] >= today), None)
    if first_future_game:
        next_game_date_str = first_future_game['date_obj'].strftime('%b %d, %Y %H:%M:%S')

    for i, main_game in enumerate(rehovot_games):
        is_past = main_game['date_obj'] < today
        is_hidden_past_game = is_past and (i != last_played_game_idx)

        row_class = "game-row"
        details_row_class = "details-panel"
        if is_hidden_past_game:
            row_class += " past-game"
            details_row_class += " past-game-details"

        date_str = main_game['date_obj'].strftime('%d.%m.%Y')
        day_he = HEBREW_WEEKDAYS.get(main_game['date_obj'].strftime('%A'), "")
        date_display = f"{day_he}, {date_str}"

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
            <td>{main_game['mahzor']}</td><td>{date_display}</td><td>{main_game['time']}</td><td class="{home_hi}">{main_game['home']}</td>
            <td class="game-result">{main_game["home_score"]}</td><td class="game-result">{main_game["away_score"]}</td>
            <td class="{away_hi}">{main_game['away']}</td><td class="action-col">{waze_btn}</td>
            <td class="action-col">{cal_btn}</td><td class="action-col">{toggle_btn}</td></tr>'''

        for game in top_games:
            date_cal_top = game['date_obj'].strftime('%Y.%m.%d')
            day_he_top = HEBREW_WEEKDAYS.get(game['date_obj'].strftime('%A'), "")
            date_display_top = f"{day_he_top}, {game['date_obj'].strftime('%d.%m.%Y')}"
            
            game_arena_safe = urllib.parse.quote_plus(game['arena'])
            waze_link_top = f"https://waze.com/ul?q={game_arena_safe}&navigate=yes"
            game_home_esc, game_away_esc, game_arena_esc = [s.replace("'", "\\'").replace('"', '&quot;') for s in [game['home'], game['away'], game['arena']]]
            
            waze_btn_top = f'<a href="{waze_link_top}" target="_blank" class="btn waze-btn"><i class="fa-brands fa-waze"></i></a>'
            cal_btn_top = f'<button onclick="addToCalendar(\'{game_home_esc} נגד {game_away_esc}\', \'{date_cal_top}\', \'{game["time"]}\', \'{game_arena_esc}\')" class="btn cal-btn"><i class="fa-regular fa-calendar-plus"></i></button>'
            
            # Add the mahzor-specific class `d{mahzor}` for toggleDetails
            current_game_html += f'''<tr class="{details_row_class} d{game['mahzor']}">
                <td>{game['mahzor']}</td><td>{date_display_top}</td><td>{game['time']}</td><td>{game['home']}</td>
                <td class="game-result">{game["home_score"]}</td><td class="game-result">{game["away_score"]}</td>
                <td>{game['away']}</td><td class="action-col">{waze_btn_top}</td>
                <td class="action-col">{cal_btn_top}</td><td class="action-col"></td></tr>'''
        
        if is_hidden_past_game:
            hidden_past_html += current_game_html
        else:
            visible_html += current_game_html
            
    final_html = visible_html
    if hidden_past_html:
        toggle_row = f'''<tr class="game-row" id="past-games-toggle-row">
            <td colspan="10" style="text-align: center; cursor: pointer;" onclick="togglePastGames()">
                <button id="past-games-toggle-btn" class="details-toggle">הצג משחקים קודמים</button>
            </td>
        </tr>'''
        final_html = toggle_row + hidden_past_html + visible_html
        
    return final_html, next_game_date_str, all_games

def main():
    """הפונקציה הראשית שמריצה את תהליך העדכון."""
    logging.info("Starting data update process.")
    
    excel_url = "https://ibasketball.co.il/league/2025-2/?feed=xlsx&league_id=119474"
    new_games_html, next_game_date_str, all_games = update_games(excel_url)

    # עדכון התובנות - כעת שולחים גם את רשימת המשחקים שחולצה מהאקסל
    gemini_model = get_gemini_model()
    new_insights_html = update_insights(gemini_model, all_games)

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

        if new_insights_html and len(new_insights_html.strip()) > 20:
            # כתיבת התשובה לסיכום הריצה ב-GitHub לצורך ניפוי שגיאות
            step_summary = os.environ.get('GITHUB_STEP_SUMMARY')
            if step_summary:
                with open(step_summary, 'a', encoding='utf-8') as sf:
                    sf.write(f"### 🤖 Gemini Insights Generated\nContent length: {len(new_insights_html)} characters.\n")
            
            # ביטוי רגולרי פשוט ואמין יותר לזיהוי ה-div
            insights_pattern = r'(<div class="insights-content">).*?(</div>)'
            if re.search(insights_pattern, html_content, flags=re.DOTALL):
                html_content = re.sub(insights_pattern, lambda m: f"{m.group(1)}\n{new_insights_html}\n{m.group(2)}", html_content, flags=re.DOTALL)
                logging.info("Insights section prepared for update.")
            else:
                logging.error("Could not find <div class='insights-content'> in index.html")
                if step_summary:
                    with open(step_summary, 'a', encoding='utf-8') as sf:
                        sf.write("⚠️ שגיאה: לא נמצא אלמנט `insights-content` בקובץ ה-HTML.\n")
        else:
            logging.warning("Insights update skipped due to missing data or error.")

        # עדכון לוח המשחקים
        if new_games_html:
            games_pattern = r'(<tbody\s+[^>]*id=["\']games-table-body["\'][^>]*>).*?(</tbody>)'
            if re.search(games_pattern, html_content, flags=re.DOTALL):
                html_content = re.sub(games_pattern, lambda m: f"{m.group(1)}\n{new_games_html}\n{m.group(2)}", html_content, flags=re.DOTALL)
                logging.info("Games schedule prepared for update.")
            else:
                logging.error("Could not find <tbody id='games-table-body'> in index.html")
        else:
            logging.warning("Games schedule is empty. HTML will not be updated for games.")

        if next_game_date_str:
            timer_pattern = r'(const countDownDate = new Date\(").*?("\)\.getTime\(\);)'
            html_content = re.sub(timer_pattern, rf'\g<1>{next_game_date_str}\g<2>', html_content)
            logging.info(f"Timer updated to: {next_game_date_str}")

        with open('index.html', 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        logging.info("index.html file updated successfully.")

    except IOError as e:
        logging.error(f"Error reading or writing to index.html: {e}")

if __name__ == "__main__":
    main()
