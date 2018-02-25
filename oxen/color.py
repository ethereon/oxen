def colorant(color_code):
    prefix = '\033[' + str(color_code) + 'm'

    def color_text(text):
        return prefix + text + '\033[0m'

    return color_text


class ColorText:
    blue = colorant(94)
    green = colorant(92)
    magenta = colorant(95)
    red = colorant(91)
    yellow = colorant(93)


def status_ok(tag, msg):
    print(f'{ColorText.green(tag) + ":":20} {msg}')
