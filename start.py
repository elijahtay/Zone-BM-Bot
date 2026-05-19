from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from store import set_user_team, get_user_team, get_all_teams


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message + team selection."""
    user = update.effective_user
    current_team = get_user_team(user.id)

    teams = get_all_teams()
    keyboard = [
        [InlineKeyboardButton(f"👥 {team}", callback_data=f"team_{team}")]
        for team in teams
    ]

    if current_team:
        keyboard.append([
            InlineKeyboardButton("📋 View My Checklist", callback_data="view_checklist")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = (
        f"👋 Hi {user.first_name}! Welcome to the *FM Checklist Bot*.\n\n"
        f"{'✅ You are currently in *' + current_team + '*.' + chr(10) + chr(10) if current_team else ''}"
        "Please select your team to get started:"
    )

    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)


async def select_team_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle team selection button press."""
    query = update.callback_query
    await query.answer()

    team_name = query.data.replace("team_", "", 1)
    user = update.effective_user
    set_user_team(user.id, team_name)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 View Checklist", callback_data="view_checklist")],
        [InlineKeyboardButton("📊 My Team's Progress", callback_data="progress")],
    ])

    await query.edit_message_text(
        f"✅ You've joined *{team_name}*!\n\n"
        "What would you like to do?",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
