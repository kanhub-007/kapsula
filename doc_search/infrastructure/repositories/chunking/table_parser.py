"""HTML table to natural language transformation."""

import html.parser


class TableParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = []
        self.current_cell = []
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self.in_cell = True
            self.current_cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.in_cell = False
            self.current_row.append("".join(self.current_cell).strip())
        elif tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
                self.current_row = []

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell.append(data)


def transform_table_to_text(table_html: str) -> str:
    parser = TableParser()
    try:
        parser.feed(table_html)
    except Exception:
        return table_html

    if len(parser.rows) < 2:
        return table_html

    headers = parser.rows[0]
    data_rows = parser.rows[1:]
    result_lines = []
    for row in data_rows:
        if len(row) != len(headers):
            continue
        parts = [f"{h}: {v}" for h, v in zip(headers, row)]
        result_lines.append(", ".join(parts) + ".")

    return "\n".join(result_lines) if result_lines else table_html
