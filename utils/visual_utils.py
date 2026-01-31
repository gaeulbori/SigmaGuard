import unicodedata

class VisualUtils:
    @staticmethod
    def get_visual_width(s):
        width = 0
        for char in str(s):
            if unicodedata.east_asian_width(char) in ('W', 'F'):
                width += 2
            else:
                width += 1
        return width

    @staticmethod
    def pad_visual(text, width, align='center'):
        text = str(text)
        curr_w = VisualUtils.get_visual_width(text)
        padding = max(0, width - curr_w)
        if align == 'left': return text + (' ' * padding)
        elif align == 'right': return (' ' * padding) + text
        else:
            left_p = padding // 2
            right_p = padding - left_p
            return (' ' * left_p) + text + (' ' * right_p)