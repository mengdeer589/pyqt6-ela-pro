"""Markdown 主题与排版 token 注册表。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QFont


_QUOTE_LEFT_MARGIN = 20.0

_HEADING_TYPOGRAPHY = {
    1: (1.5, 24.0, 8.0, 135.0, QFont.Weight.DemiBold),
    2: (1.3, 20.0, 8.0, 140.0, QFont.Weight.DemiBold),
    3: (1.15, 16.0, 6.0, 145.0, QFont.Weight.DemiBold),
    4: (1.05, 12.0, 6.0, 150.0, QFont.Weight.DemiBold),
    5: (1.0, 12.0, 6.0, 150.0, QFont.Weight.DemiBold),
    6: (1.0, 12.0, 6.0, 150.0, QFont.Weight.DemiBold),
}

_BODY_LINE_HEIGHT = 165.0

_LIST_ITEM_MARGIN = 4.0

_QUOTE_BLOCK_MARGIN = 8.0

_PARAGRAPH_MARGIN = 10.0

_TABLE_BLOCK_MARGIN = 10.0

_QUOTE_RAIL_WIDTH = 3.0

_QUOTE_RAIL_INSET = 4.0

_HR_LINE_WIDTH = 1.0

_CODE_CARD_RADIUS = 4.0

_INLINE_CODE_PADDING = 3.0

_INLINE_CODE_RADIUS = 3.0

_MD_LAYOUT_DEFAULTS = {
    "heading": dict(_HEADING_TYPOGRAPHY),
    "body_font_family": "",
    "content_max_width": 0,
    "surface": {"light": None, "dark": None},
    "body_line_height": _BODY_LINE_HEIGHT,
    "paragraph_margin": _PARAGRAPH_MARGIN,
    "list_item_margin": _LIST_ITEM_MARGIN,
    "table_block_margin": _TABLE_BLOCK_MARGIN,
    "quote": {
        "rail_width": _QUOTE_RAIL_WIDTH,
        "rail_inset": _QUOTE_RAIL_INSET,
        "left_margin": _QUOTE_LEFT_MARGIN,
        "block_margin": _QUOTE_BLOCK_MARGIN,
        "italic": False,
        "background": False,
        "background_alpha": 0.0,
        "background_color": "accent",
        "rail_color": "muted",
        "text_color": "quote",
    },
    "table": {
        "top_padding": 8.0,
        "bottom_padding": 8.0,
        "left_padding": 12.0,
        "right_padding": 12.0,
        "header_background": False,
        "header_background_alpha": 0.04,
        "header_weight": int(QFont.Weight.DemiBold),
        "zebra": False,
        "border_alpha": 0.10,
        "border_width": 1.0,
    },
    "code": {
        "radius": _CODE_CARD_RADIUS,
        "border": True,
        "background_alpha": 0.035,
        "border_alpha": 0.10,
        "line_height": 150.0,
        "font_scale": 0.95,
    },
    "inline_code": {
        "border": False,
        "radius": _INLINE_CODE_RADIUS,
        "padding": _INLINE_CODE_PADDING,
        "background_alpha": 0.06,
    },
    "hr": {"width": _HR_LINE_WIDTH, "color": "border"},
    "link": {"underline": False},
    "heading_rule": {
        "levels": (),
        "width": 1.0,
        "color": "border",
        "left_width": 0.0,
        "left_color": "accent",
        "left_gap": 8.0,
    },
}

_MD_LAYOUTS = {
    "lark": {
        "heading": {
            1: (1.625, 21.0, 8.0, 140.0, QFont.Weight.DemiBold),
            2: (1.375, 18.0, 8.0, 140.0, QFont.Weight.DemiBold),
            3: (1.25, 16.0, 8.0, 140.0, QFont.Weight.DemiBold),
            4: (1.125, 14.0, 8.0, 140.0, QFont.Weight.DemiBold),
            5: (1.0, 13.0, 8.0, 140.0, QFont.Weight.DemiBold),
            6: (1.0, 13.0, 8.0, 140.0, QFont.Weight.DemiBold),
        },
        "body_line_height": 168.0,
        "paragraph_margin": 8.0,
        "table_block_margin": 8.0,
        "quote": {
            "rail_width": 2.0,
            "rail_color": "accent",
            "background": False,
            "italic": False,
        },
        "table": {
            "header_background": False,
            "header_weight": int(QFont.Weight.DemiBold),
            "zebra": False,
            "border_alpha": 0.12,
        },
        "code": {"line_height": 160.0, "font_scale": 0.92},
        "inline_code": {"border": True, "radius": 4.0},
    },
    "typo": {
        "heading": {
            1: (2.0, 20.0, 10.0, 135.0, QFont.Weight.Light),
            2: (1.8, 20.0, 10.0, 135.0, QFont.Weight.Light),
            3: (1.6, 20.0, 10.0, 135.0, QFont.Weight.Light),
            4: (1.4, 20.0, 10.0, 135.0, QFont.Weight.Light),
            5: (1.2, 20.0, 10.0, 135.0, QFont.Weight.Light),
            6: (1.2, 20.0, 10.0, 135.0, QFont.Weight.Light),
        },
        "body_line_height": 180.0,
        "paragraph_margin": 15.0,
        "list_item_margin": 3.0,
        "table_block_margin": 13.0,
        "quote": {
            "rail_width": 1.0,
            "rail_color": "accent",
            "left_margin": 26.0,
            "block_margin": 13.0,
            "background": False,
            "italic": False,
        },
        "table": {
            "top_padding": 6.5,
            "bottom_padding": 6.5,
            "left_padding": 13.0,
            "right_padding": 13.0,
            "header_background": True,
            "header_weight": int(QFont.Weight.Bold),
            "border_alpha": 0.18,
        },
        "code": {"radius": 0.0, "border_alpha": 0.16},
        "inline_code": {"border": False, "radius": 0.0, "background_alpha": 0.0},
        "link": {"underline": True},
    },
    "vue": {
        "heading": {
            1: (2.2, 30.0, 10.0, 130.0, QFont.Weight.Bold),
            2: (1.75, 22.0, 10.0, 125.0, QFont.Weight.Bold),
            3: (1.4, 18.0, 8.0, 143.0, QFont.Weight.Bold),
            4: (1.2, 16.0, 8.0, 150.0, QFont.Weight.Bold),
            5: (1.0, 16.0, 8.0, 150.0, QFont.Weight.Bold),
            6: (1.0, 16.0, 8.0, 150.0, QFont.Weight.Bold),
        },
        "body_line_height": 160.0,
        "table_block_margin": 10.0,
        "quote": {
            "rail_width": 4.0,
            "rail_color": "accent",
            "background": True,
            "background_alpha": 0.10,
            "background_color": "accent",
            "block_margin": 10.0,
        },
        "table": {
            "top_padding": 6.0,
            "bottom_padding": 6.0,
            "left_padding": 13.0,
            "right_padding": 13.0,
            "header_background": True,
            "header_weight": int(QFont.Weight.Bold),
            "zebra": True,
            "border_alpha": 0.18,
        },
        "code": {"radius": 2.0, "border": False, "background_alpha": 0.06},
        "inline_code": {"border": False, "radius": 2.0, "padding": 2.0},
        "heading_rule": {"levels": (2,), "width": 1.0, "color": "border"},
    },
    "indigo": {
        "heading": {
            1: (1.5, 24.0, 16.0, 125.0, QFont.Weight.DemiBold),
            2: (1.3, 20.0, 16.0, 125.0, QFont.Weight.DemiBold),
            3: (1.15, 16.0, 10.0, 130.0, QFont.Weight.DemiBold),
            4: (1.05, 12.0, 10.0, 135.0, QFont.Weight.DemiBold),
            5: (1.0, 12.0, 10.0, 135.0, QFont.Weight.DemiBold),
            6: (1.0, 12.0, 10.0, 135.0, QFont.Weight.DemiBold),
        },
        "body_line_height": 180.0,
        "table_block_margin": 10.0,
        "quote": {
            "rail_width": 4.0,
            "rail_color": "accent",
            "background": True,
            "background_alpha": 0.10,
            "background_color": "accent",
            "block_margin": 10.0,
        },
        "table": {
            "header_background": False,
            "header_weight": int(QFont.Weight.DemiBold),
            "border_alpha": 0.12,
        },
        "code": {"radius": 4.0, "border_alpha": 0.12},
        "inline_code": {"border": False, "radius": 4.0, "background_alpha": 0.10},
        "heading_rule": {
            "levels": (1, 2),
            "width": 1.0,
            "color": "border",
            "left_width": 6.0,
            "left_color": "accent",
            "left_gap": 8.0,
        },
    },
    # 暖纸阅读：衬线正文 + 820px 阅读列 + 暖纸底
    "paper": {
        "heading": {
            1: (1.45, 28.0, 10.0, 138.0, QFont.Weight.DemiBold),
            2: (1.25, 22.0, 8.0, 142.0, QFont.Weight.DemiBold),
            3: (1.12, 16.0, 8.0, 145.0, QFont.Weight.DemiBold),
            4: (1.02, 12.0, 6.0, 150.0, QFont.Weight.DemiBold),
            5: (1.0, 12.0, 6.0, 150.0, QFont.Weight.DemiBold),
            6: (1.0, 12.0, 6.0, 150.0, QFont.Weight.DemiBold),
        },
        "body_font_family": "serif",
        "content_max_width": 820,
        "surface": {"light": "#f7f1e3", "dark": "#1f1b17"},
        "body_line_height": 176.0,
        "paragraph_margin": 12.0,
        "list_item_margin": 5.0,
        "table_block_margin": 12.0,
        "quote": {
            "rail_width": 3.0,
            "rail_color": "muted",
            "block_margin": 10.0,
            "text_color": "muted",
        },
        "table": {
            "top_padding": 7.0,
            "bottom_padding": 7.0,
            "header_background": True,
            "header_background_alpha": 0.05,
            "border_alpha": 0.12,
        },
        "code": {
            "radius": 3.0,
            "border": True,
            "border_alpha": 0.12,
            "background_alpha": 0.045,
        },
        "inline_code": {"border": False, "radius": 3.0, "background_alpha": 0.07},
    },
    # GitHub Primer：README / 技术文档标准基线
    "github": {
        "heading": {
            1: (2.0, 24.0, 8.0, 135.0, QFont.Weight.Bold),
            2: (1.5, 20.0, 8.0, 140.0, QFont.Weight.Bold),
            3: (1.25, 16.0, 8.0, 145.0, QFont.Weight.Bold),
            4: (1.0, 10.0, 6.0, 150.0, QFont.Weight.DemiBold),
            5: (1.0, 10.0, 6.0, 150.0, QFont.Weight.DemiBold),
            6: (0.9, 8.0, 6.0, 150.0, QFont.Weight.DemiBold),
        },
        "content_max_width": 980,
        "body_line_height": 160.0,
        "paragraph_margin": 8.0,
        "list_item_margin": 3.0,
        "table_block_margin": 12.0,
        "heading_rule": {"levels": (1, 2), "width": 1.0, "color": "border"},
        "quote": {
            "rail_width": 4.0,
            "rail_color": "border",
            "block_margin": 8.0,
            "text_color": "muted",
        },
        "table": {
            "top_padding": 6.0,
            "bottom_padding": 6.0,
            "header_background": True,
            "header_background_alpha": 0.045,
            "border_alpha": 0.12,
        },
        "code": {
            "radius": 6.0,
            "border": True,
            "border_alpha": 0.12,
            "background_alpha": 0.04,
        },
        "inline_code": {"border": False, "radius": 4.0, "background_alpha": 0.08},
    },
    # Nord：中性冷灰，长文与代码都克制
    "nord": {
        "heading": {
            1: (1.5, 26.0, 10.0, 135.0, QFont.Weight.DemiBold),
            2: (1.3, 20.0, 8.0, 140.0, QFont.Weight.DemiBold),
            3: (1.15, 16.0, 8.0, 145.0, QFont.Weight.DemiBold),
            4: (1.05, 12.0, 6.0, 150.0, QFont.Weight.DemiBold),
            5: (1.0, 12.0, 6.0, 150.0, QFont.Weight.DemiBold),
            6: (1.0, 12.0, 6.0, 150.0, QFont.Weight.DemiBold),
        },
        "body_line_height": 168.0,
        "paragraph_margin": 10.0,
        "quote": {
            "rail_width": 3.0,
            "rail_color": "accent",
            "background": True,
            "background_alpha": 0.06,
            "block_margin": 10.0,
        },
        "table": {
            "top_padding": 7.0,
            "bottom_padding": 7.0,
            "header_background": True,
            "header_background_alpha": 0.06,
            "border_alpha": 0.14,
        },
        "code": {
            "radius": 6.0,
            "border": True,
            "border_alpha": 0.14,
            "background_alpha": 0.05,
        },
        "inline_code": {"border": False, "radius": 4.0, "background_alpha": 0.08},
    },
}

_MD_THEME_SEMANTIC_KEYS = (
    "heading",
    "strong",
    "emphasis",
    "code",
    "link",
    "quote",
    "list",
    "mark",
)

_MD_THEME_SYNTAX_KEYS = (
    "keyword",
    "constant",
    "type",
    "function",
    "class",
    "decorator",
    "builtin",
    "attribute",
    "tag",
    "string",
    "number",
    "comment",
    "operator",
)

_MD_THEMES = {
    # Bear / Ink：正文墨色、单一蓝链接、柔和高亮；只有代码块保留语法色
    "bear": {
        "light": {
            "semantic": {
                "heading": "#262626",
                "strong": "#222222",
                "emphasis": "#222222",
                "code": "#424242",
                "link": "#2478c5",
                "quote": "#6f6f6f",
                "list": "#2478c5",
                "mark": "#fcffc0",
            },
            "syntax": {
                "keyword": "#2478c5",
                "constant": "#0b5d83",
                "type": "#0e73a2",
                "function": "#0e73a2",
                "class": "#0e73a2",
                "decorator": "#950980",
                "builtin": "#0e73a2",
                "attribute": "#950980",
                "tag": "#1b00ce",
                "string": "#b43d15",
                "number": "#0b5d83",
                "comment": "#575757",
                "operator": "#920448",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#cbdee5",
                "strong": "#dddddd",
                "emphasis": "#dddddd",
                "code": "#fefeff",
                "link": "#6bcafb",
                "quote": "#8a9299",
                "list": "#6bcafb",
                "mark": "#4a4420",
            },
            "syntax": {
                "keyword": "#aedada",
                "constant": "#aac97f",
                "type": "#cbdee5",
                "function": "#6bcafb",
                "class": "#cbdee5",
                "decorator": "#ff9dd1",
                "builtin": "#6bcafb",
                "attribute": "#fd8273",
                "tag": "#e6772f",
                "string": "#aac97f",
                "number": "#aac97f",
                "comment": "#7f8c97",
                "operator": "#aedada",
            },
        },
    },
    # Lark（飞书文档）：白底、蓝色单强调、8px 节奏
    "lark": {
        "light": {
            "semantic": {
                "heading": "#1f2329",
                "strong": "#1f2329",
                "emphasis": "#1f2329",
                "code": "#1f2329",
                "link": "#3370ff",
                "quote": "#646a73",
                "list": "#3370ff",
                "mark": "#fff67a",
            },
            "syntax": {
                "keyword": "#cf222e",
                "constant": "#0550ae",
                "type": "#953800",
                "function": "#8250df",
                "class": "#953800",
                "decorator": "#8250df",
                "builtin": "#0550ae",
                "attribute": "#0550ae",
                "tag": "#116329",
                "string": "#0a3069",
                "number": "#0550ae",
                "comment": "#59636e",
                "operator": "#59636e",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#f0f3f8",
                "strong": "#e8eaed",
                "emphasis": "#e8eaed",
                "code": "#e8eaed",
                "link": "#4c8dff",
                "quote": "#a8b0ba",
                "list": "#4c8dff",
                "mark": "#5a4b1f",
            },
            "syntax": {
                "keyword": "#ff7b72",
                "constant": "#79c0ff",
                "type": "#ffa657",
                "function": "#d2a8ff",
                "class": "#ffa657",
                "decorator": "#d2a8ff",
                "builtin": "#79c0ff",
                "attribute": "#79c0ff",
                "tag": "#7ee787",
                "string": "#a5d6ff",
                "number": "#79c0ff",
                "comment": "#8b949e",
                "operator": "#c9d1d9",
            },
        },
        "layout": _MD_LAYOUTS["lark"],
    },
    # Typo.css：细标题、青绿链接、文学感
    "typo": {
        "light": {
            "semantic": {
                "heading": "#000000",
                "strong": "#000000",
                "emphasis": "#000000",
                "code": "#000000",
                "link": "#1abc9c",
                "quote": "#999999",
                "list": "#1abc9c",
                "mark": "#fffdd1",
            },
            "syntax": {
                "keyword": "#277fbe",
                "constant": "#1b6498",
                "type": "#66a329",
                "function": "#66a329",
                "class": "#66a329",
                "decorator": "#66a329",
                "builtin": "#66a329",
                "attribute": "#66a329",
                "tag": "#1b6498",
                "string": "#277fbe",
                "number": "#1b6498",
                "comment": "#8a9a8a",
                "operator": "#1b6498",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#f2f2ef",
                "strong": "#ffffff",
                "emphasis": "#f2f2ef",
                "code": "#f2f2ef",
                "link": "#2dd4bf",
                "quote": "#9aa5a0",
                "list": "#2dd4bf",
                "mark": "#5a5a2a",
            },
            "syntax": {
                "keyword": "#2dd4bf",
                "constant": "#f0c674",
                "type": "#81a2be",
                "function": "#b5bd68",
                "class": "#81a2be",
                "decorator": "#c678dd",
                "builtin": "#81a2be",
                "attribute": "#de935f",
                "tag": "#cc6666",
                "string": "#b5bd68",
                "number": "#f0c674",
                "comment": "#7f8c8d",
                "operator": "#c5c8c6",
            },
        },
        "layout": _MD_LAYOUTS["typo"],
    },
    # Vue 文档：绿色强调、全网格表格、代码浅灰
    "vue": {
        "light": {
            "semantic": {
                "heading": "#34495e",
                "strong": "#34495e",
                "emphasis": "#34495e",
                "code": "#e96900",
                "link": "#42b983",
                "quote": "#777777",
                "list": "#42b983",
                "mark": "#fff7a8",
            },
            "syntax": {
                "keyword": "#277fbe",
                "constant": "#1b6498",
                "type": "#66a329",
                "function": "#66a329",
                "class": "#66a329",
                "decorator": "#66a329",
                "builtin": "#66a329",
                "attribute": "#66a329",
                "tag": "#1b6498",
                "string": "#277fbe",
                "number": "#1b6498",
                "comment": "#8a9a8a",
                "operator": "#1b6498",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#e6e6e6",
                "strong": "#ffffff",
                "emphasis": "#e6e6e6",
                "code": "#ff9d5c",
                "link": "#4ade80",
                "quote": "#a0a0a0",
                "list": "#4ade80",
                "mark": "#5a4b1f",
            },
            "syntax": {
                "keyword": "#82aaff",
                "constant": "#f78c6c",
                "type": "#c3e88d",
                "function": "#c3e88d",
                "class": "#c3e88d",
                "decorator": "#c792ea",
                "builtin": "#c3e88d",
                "attribute": "#ffcb6b",
                "tag": "#f07178",
                "string": "#c3e88d",
                "number": "#f78c6c",
                "comment": "#7f8c8d",
                "operator": "#89ddff",
            },
        },
        "layout": _MD_LAYOUTS["vue"],
    },
    # Ayu：暖纸色 + 橙色强调；深色 Ayu Mirage
    "ayu": {
        "light": {
            "semantic": {
                "heading": "#4d5255",
                "strong": "#3a3a3a",
                "emphasis": "#6b6884",
                "code": "#272d38",
                "link": "#e66700",
                "quote": "#8d8f95",
                "list": "#ff6a00",
                "mark": "#e6f9bd",
            },
            "syntax": {
                "keyword": "#2576b1",
                "constant": "#0087b2",
                "type": "#357f1e",
                "function": "#2576b1",
                "class": "#357f1e",
                "decorator": "#ba2ba3",
                "builtin": "#2576b1",
                "attribute": "#ba2ba3",
                "tag": "#ba2ba3",
                "string": "#357f1e",
                "number": "#0087b2",
                "comment": "#7f7e7d",
                "operator": "#6b6884",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#9faab9",
                "strong": "#d9d7d1",
                "emphasis": "#d9d7d1",
                "code": "#cfd0cb",
                "link": "#fecb66",
                "quote": "#787e8c",
                "list": "#fecb66",
                "mark": "#116e54",
            },
            "syntax": {
                "keyword": "#fea759",
                "constant": "#b0e27d",
                "type": "#76d0ff",
                "function": "#fea759",
                "class": "#76d0ff",
                "decorator": "#7390c9",
                "builtin": "#fea759",
                "attribute": "#f18779",
                "tag": "#f18779",
                "string": "#b0e27d",
                "number": "#b0e27d",
                "comment": "#7e91a2",
                "operator": "#d9d7d1",
            },
        },
    },
    # Solarized：MWeb Bear 配套的 Light / Dark
    "solarized": {
        "light": {
            "semantic": {
                "heading": "#3b4f54",
                "strong": "#3b4f54",
                "emphasis": "#3b4f54",
                "code": "#657b83",
                "link": "#ac7514",
                "quote": "#71807d",
                "list": "#a56812",
                "mark": "#caff93",
            },
            "syntax": {
                "keyword": "#1082b7",
                "constant": "#107fb2",
                "type": "#d33905",
                "function": "#1082b7",
                "class": "#d33905",
                "decorator": "#cf0cb2",
                "builtin": "#1082b7",
                "attribute": "#cf0cb2",
                "tag": "#d33905",
                "string": "#d33905",
                "number": "#107fb2",
                "comment": "#838383",
                "operator": "#657b83",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#abb5b4",
                "strong": "#9ba6a4",
                "emphasis": "#9ba6a4",
                "code": "#94a2a2",
                "link": "#3fc6b4",
                "quote": "#6a8690",
                "list": "#2c9285",
                "mark": "#1f0032",
            },
            "syntax": {
                "keyword": "#69b5d8",
                "constant": "#31b1ed",
                "type": "#fc8a64",
                "function": "#69b5d8",
                "class": "#fc8a64",
                "decorator": "#6952ff",
                "builtin": "#69b5d8",
                "attribute": "#d40cb6",
                "tag": "#fc8a64",
                "string": "#fc8a64",
                "number": "#31b1ed",
                "comment": "#a6a6a6",
                "operator": "#94a2a2",
            },
        },
    },
    # Indigo：紫蓝强调、标题左侧竖线、淡蓝引用底
    "indigo": {
        "light": {
            "semantic": {
                "heading": "#4c51bf",
                "strong": "#5a67d8",
                "emphasis": "#595959",
                "code": "#5a67d8",
                "link": "#5a67d8",
                "quote": "#667eea",
                "list": "#5a67d8",
                "mark": "#fff67a",
            },
            "syntax": {
                "keyword": "#5a67d8",
                "constant": "#805ad5",
                "type": "#3182ce",
                "function": "#3182ce",
                "class": "#3182ce",
                "decorator": "#b83280",
                "builtin": "#3182ce",
                "attribute": "#b83280",
                "tag": "#e53e3e",
                "string": "#38a169",
                "number": "#805ad5",
                "comment": "#718096",
                "operator": "#4a5568",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#e2e8f0",
                "strong": "#c3dafe",
                "emphasis": "#e2e8f0",
                "code": "#c3dafe",
                "link": "#7f9cf5",
                "quote": "#a3bffa",
                "list": "#7f9cf5",
                "mark": "#4a3f8a",
            },
            "syntax": {
                "keyword": "#7f9cf5",
                "constant": "#f6ad55",
                "type": "#63b3ed",
                "function": "#63b3ed",
                "class": "#63b3ed",
                "decorator": "#f687b3",
                "builtin": "#63b3ed",
                "attribute": "#f687b3",
                "tag": "#fc8181",
                "string": "#68d391",
                "number": "#f6ad55",
                "comment": "#a0aec0",
                "operator": "#e2e8f0",
            },
        },
        "layout": _MD_LAYOUTS["indigo"],
    },
    # Paper：暖纸底 + 衬线正文 + 棕色强调
    "paper": {
        "light": {
            "semantic": {
                "heading": "#3a3128",
                "strong": "#2f2820",
                "emphasis": "#2f2820",
                "code": "#5a4a3a",
                "link": "#8b5e34",
                "quote": "#7a6a58",
                "list": "#a06a3a",
                "mark": "#f0dfae",
            },
            "syntax": {
                "keyword": "#9c3f2f",
                "constant": "#8a5d2b",
                "type": "#6f5b3e",
                "function": "#7b4f2a",
                "class": "#6e4a2e",
                "decorator": "#8b5e34",
                "builtin": "#7b5c3e",
                "attribute": "#8b5e34",
                "tag": "#9c3f2f",
                "string": "#5f6f3a",
                "number": "#8a5d2b",
                "comment": "#9a8b78",
                "operator": "#6b5a48",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#e8ddc9",
                "strong": "#f0e6d2",
                "emphasis": "#f0e6d2",
                "code": "#d8c8b0",
                "link": "#d7a06a",
                "quote": "#b8a890",
                "list": "#d7a06a",
                "mark": "#5a4a1f",
            },
            "syntax": {
                "keyword": "#e6a17a",
                "constant": "#d8b46a",
                "type": "#c9b38f",
                "function": "#e0b87a",
                "class": "#d7a06a",
                "decorator": "#d7a06a",
                "builtin": "#c9b38f",
                "attribute": "#d7a06a",
                "tag": "#e6a17a",
                "string": "#a8b87a",
                "number": "#d8b46a",
                "comment": "#8f806c",
                "operator": "#c9b8a0",
            },
        },
        "layout": _MD_LAYOUTS["paper"],
    },
    # GitHub Primer：标准 README 色板
    "github": {
        "light": {
            "semantic": {
                "heading": "#1f2328",
                "strong": "#1f2328",
                "emphasis": "#1f2328",
                "code": "#1f2328",
                "link": "#0969da",
                "quote": "#59636e",
                "list": "#0969da",
                "mark": "#fff8c5",
            },
            "syntax": {
                "keyword": "#cf222e",
                "constant": "#0550ae",
                "type": "#953800",
                "function": "#8250df",
                "class": "#8250df",
                "decorator": "#8250df",
                "builtin": "#0550ae",
                "attribute": "#0550ae",
                "tag": "#116329",
                "string": "#0a3069",
                "number": "#0550ae",
                "comment": "#6e7781",
                "operator": "#cf222e",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#f0f6fc",
                "strong": "#f0f6fc",
                "emphasis": "#f0f6fc",
                "code": "#f0f6fc",
                "link": "#4493f8",
                "quote": "#9198a1",
                "list": "#4493f8",
                "mark": "#664d03",
            },
            "syntax": {
                "keyword": "#ff7b72",
                "constant": "#79c0ff",
                "type": "#ffa657",
                "function": "#d2a8ff",
                "class": "#d2a8ff",
                "decorator": "#d2a8ff",
                "builtin": "#79c0ff",
                "attribute": "#79c0ff",
                "tag": "#7ee787",
                "string": "#a5d6ff",
                "number": "#79c0ff",
                "comment": "#8b949e",
                "operator": "#ff7b72",
            },
        },
        "layout": _MD_LAYOUTS["github"],
    },
    # Nord：Polar Night / Snow Storm / Frost / Aurora
    "nord": {
        "light": {
            "semantic": {
                "heading": "#2e3440",
                "strong": "#2e3440",
                "emphasis": "#2e3440",
                "code": "#3b4252",
                "link": "#5e81ac",
                "quote": "#4c566a",
                "list": "#5e81ac",
                "mark": "#ebcb8b",
            },
            "syntax": {
                "keyword": "#5e81ac",
                "constant": "#8f5f8f",
                "type": "#4f7f7f",
                "function": "#3f6f85",
                "class": "#4f7f7f",
                "decorator": "#8f5f8f",
                "builtin": "#4f7f7f",
                "attribute": "#3f6f85",
                "tag": "#a34a4a",
                "string": "#5f7f4f",
                "number": "#8f5f8f",
                "comment": "#6f7a8a",
                "operator": "#3b4252",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#eceff4",
                "strong": "#eceff4",
                "emphasis": "#eceff4",
                "code": "#e5e9f0",
                "link": "#88c0d0",
                "quote": "#a3aab8",
                "list": "#81a1c1",
                "mark": "#6b5a2a",
            },
            "syntax": {
                "keyword": "#81a1c1",
                "constant": "#b48ead",
                "type": "#8fbcbb",
                "function": "#88c0d0",
                "class": "#8fbcbb",
                "decorator": "#b48ead",
                "builtin": "#8fbcbb",
                "attribute": "#88c0d0",
                "tag": "#bf616a",
                "string": "#a3be8c",
                "number": "#b48ead",
                "comment": "#7b88a1",
                "operator": "#d8dee9",
            },
        },
        "layout": _MD_LAYOUTS["nord"],
    },
}

_BUILTIN_MD_THEMES = frozenset(_MD_THEMES)

_DEFAULT_MD_THEME = "bear"


def _md_theme_spec(name: str) -> dict:
    """取主题定义（未知名称回落默认主题）。"""
    return _MD_THEMES.get(name) or _MD_THEMES[_DEFAULT_MD_THEME]


def _merge_md_layout(base: dict, patch) -> dict:
    """把主题排版覆盖合并到默认布局（只合并已知键）。"""
    merged = {
        key: (dict(value) if isinstance(value, dict) else value)
        for key, value in base.items()
    }
    if isinstance(patch, dict):
        for key, value in patch.items():
            if key not in merged:
                continue
            if isinstance(merged[key], dict) and isinstance(value, dict):
                for subkey, subvalue in value.items():
                    if subkey in merged[key]:
                        merged[key][subkey] = subvalue
            else:
                merged[key] = value
    return merged


def _md_layout_spec(name: str) -> dict:
    """取主题排版（未覆盖的 token 继承 Bear / Ink 默认）。"""
    return _merge_md_layout(_MD_LAYOUT_DEFAULTS, _md_theme_spec(name).get("layout"))


def markdownThemes() -> list:
    """全部内置 / 已注册的 markdown 主题名（按注册顺序）。"""
    return list(_MD_THEMES)


def defaultMarkdownTheme() -> str:
    """获取新建查看器使用的默认 markdown 主题名。"""
    return _DEFAULT_MD_THEME


def setDefaultMarkdownTheme(name: str) -> bool:
    """设置默认 markdown 主题（只影响之后新建的查看器，不重渲染已有实例）；
    主题存在才返回 ``True``。
    """
    global _DEFAULT_MD_THEME
    if name not in _MD_THEMES:
        return False
    _DEFAULT_MD_THEME = name
    return True


def registerMarkdownTheme(
    name: str,
    light: Optional[dict] = None,
    dark: Optional[dict] = None,
    layout: Optional[dict] = None,
) -> None:
    """注册 / 覆盖一套 markdown 主题（``name`` 同名即覆盖）。

    ``light`` / ``dark`` 是 ``{"semantic": {...}, "syntax": {...}}``，可省略或只
    给部分键（其余合并自默认主题）。``layout`` 可覆盖标题 / 正文 / 引用 / 表格 /
    代码等排版 token，以及 ``body_font_family``（``""`` / ``"serif"`` / 字体族）、
    ``content_max_width``（阅读列像素，0 = 不限）与 ``surface``（``light`` /
    ``dark`` 页面底色，``None`` = 跟随 eTheme）；未写的键继承 Bear / Ink 默认。
    ``semantic`` 的 8 个键：
    ``heading`` / ``strong`` / ``emphasis`` / ``code`` / ``link`` / ``quote`` /
    ``list``（任务勾选框等列表标记；列表**文字**保持正文色 —— Qt 的 bullet 由
    调色板绘制、字符格式染不上）/ ``mark``（``==高亮==`` 底色的基色，与背景混合
    后使用）。
    """
    if not isinstance(name, str) or not name:
        raise ValueError("registerMarkdownTheme: 主题名不能为空")
    base = _MD_THEMES.get(_DEFAULT_MD_THEME) or {}
    entry = {
        variant: _merge_md_variant(base.get(variant, {}), patch)
        for variant, patch in (("light", light), ("dark", dark))
    }
    if layout is not None:
        entry["layout"] = layout
    _MD_THEMES[name] = entry


def unregisterMarkdownTheme(name: str) -> bool:
    """移除已注册主题（内置主题不可移除）；返回是否移除成功。"""
    if name in _BUILTIN_MD_THEMES or name not in _MD_THEMES:
        return False
    _MD_THEMES.pop(name, None)
    return True


def _merge_md_variant(base: dict, patch: Optional[dict]) -> dict:
    """把主题补丁合并到基准变体上（只接受已存在的键与字符串值）。"""
    merged = {
        "semantic": dict(base.get("semantic") or {}),
        "syntax": dict(base.get("syntax") or {}),
    }
    if isinstance(patch, dict):
        for section in ("semantic", "syntax"):
            values = patch.get(section)
            if isinstance(values, dict):
                for key, value in values.items():
                    if key in merged[section] and isinstance(value, str):
                        merged[section][key] = value
    return merged
