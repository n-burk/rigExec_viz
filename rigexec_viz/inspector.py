"""Op inspector: what the selected node is, reads, writes, and said.

A plain Qt panel beside the noodles view. Dependency buttons jump the
view's selection (and framing) to that op, so the graph is walkable
edge by edge without touching the camera.
"""

from __future__ import annotations

from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets


def _mono(text):
    label = QtWidgets.QLabel(text)
    label.setFont(QtGui.QFont("Consolas, Menlo, monospace"))
    label.setTextInteractionFlags(
        QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


def _section(title):
    label = QtWidgets.QLabel(title)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class OpInspector(QtWidgets.QWidget):
    """Detail panel for one op node; empty-state aware."""

    navigate = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.show_empty("Select a node to inspect it.")

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def show_empty(self, message):
        self._clear()
        label = QtWidgets.QLabel(message)
        label.setWordWrap(True)
        self._layout.addWidget(label)
        self._layout.addStretch(1)

    def show_op(self, node, in_edges, out_edges, fired, duration_us=None):
        """Render one session op dict with its incident edges."""
        self._clear()
        title = QtWidgets.QLabel("[%s] %s" % (node["domain"],
                                              node.get("kind", "")))
        font = title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        title.setFont(font)
        title.setWordWrap(True)
        self._layout.addWidget(title)
        self._layout.addWidget(_mono(node.get("label", "")))
        self._layout.addWidget(_mono("id: %s" % node["id"]))

        run = "fired last generation (%d us)" % duration_us \
            if fired and duration_us is not None else \
            ("fired last generation" if fired else "dark last generation")
        self._layout.addWidget(QtWidgets.QLabel(run))

        grid = QtWidgets.QFormLayout()
        if node.get("profile"):
            grid.addRow("fires on:", _mono(node["profile"]))
        grid.addRow("level / order:",
                    QtWidgets.QLabel("%s / %s" % (node.get("level"),
                                                  node.get("order"))))
        for key in sorted(node.get("details", {})):
            grid.addRow(key + ":", _mono(str(node["details"][key])))
        self._layout.addLayout(grid)

        for key in sorted(node.get("lists", {})):
            values = node["lists"][key]
            if not values:
                continue
            self._layout.addWidget(_section(key.replace("_", " ").title()))
            self._layout.addWidget(_mono("\n".join(map(str, values))))

        self._layout.addWidget(_section("Dependencies"))
        self._layout.addWidget(self._link_row("in", in_edges))
        self._layout.addWidget(self._link_row("out", out_edges))
        self._layout.addStretch(1)

    def _link_row(self, title, edges):
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QtWidgets.QLabel(title + ":"))
        if not edges:
            layout.addWidget(QtWidgets.QLabel("-"))
        box = QtWidgets.QWidget()
        flow = QtWidgets.QVBoxLayout(box)
        flow.setContentsMargins(0, 0, 0, 0)
        for other, kind in edges[:24]:
            button = QtWidgets.QPushButton("%s (%s)" % (other, kind))
            button.clicked.connect(
                lambda _checked=False, i=other: self.navigate.emit(i))
            flow.addWidget(button)
        if len(edges) > 24:
            flow.addWidget(QtWidgets.QLabel("... %d more" % (len(edges) - 24)))
        layout.addWidget(box)
        layout.addStretch(1)
        return row
