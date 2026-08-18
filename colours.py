from colorama import init, Fore
import random

init(autoreset=True)

DISTINCT_COLOURS = [
    Fore.RED,
    Fore.GREEN,
    Fore.YELLOW,
    Fore.BLUE,
    Fore.MAGENTA,
    Fore.CYAN,
]

COLOUR_VARIANTS = {
    Fore.RED:     [Fore.LIGHTRED_EX],
    Fore.GREEN:   [Fore.LIGHTGREEN_EX],
    Fore.YELLOW:  [Fore.LIGHTYELLOW_EX],
    Fore.BLUE:    [Fore.LIGHTBLUE_EX],
    Fore.MAGENTA: [Fore.LIGHTMAGENTA_EX],
    Fore.CYAN:    [Fore.LIGHTCYAN_EX],
    Fore.BLACK:   [Fore.LIGHTBLACK_EX],
}

last_used_colour = None

def get_next_colour():
    global last_used_colour

    if last_used_colour is None:
        last_used_colour = random.choice(DISTINCT_COLOURS)
        return last_used_colour

    excluded = [last_used_colour] + COLOUR_VARIANTS.get(last_used_colour, [])
    available = [c for c in DISTINCT_COLOURS if c not in excluded]

    if not available:
        last_used_colour = random.choice(DISTINCT_COLOURS)
        return last_used_colour

    last_used_colour = random.choice(available)
    return last_used_colour
##