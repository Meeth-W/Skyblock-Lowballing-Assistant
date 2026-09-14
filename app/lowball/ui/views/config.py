"""Settings, rules and pricing, all editable in the app.

Three things live here, and they are separate because they are different kinds
of thing.

Settings are a form. Rules are a list you build from menus -- they used to be
YAML you typed, and a typo produced a rule that parsed, loaded and silently
never fired, which is the worst failure available to something whose job is to
stop you overpaying. Pricing is a table of numbers with a button that fetches
most of them from the bazaar, because the alternative was hand-copying forty
book prices that move every week.

All three still write the same YAML files, so a rule set can be diffed, shared
and hand-edited by anyone who prefers to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...api.bazaar import NOT_ON_BAZAAR, refresh_values
from ...config import save_settings
from ...money import format_coins, format_coins_exact, parse_coins
from ...pricing.values import ValueTable, load_values, save_values
from ...rules import Rule, RuleError, dump_rules, load_rules
from ..dialogs.rule_editor import RuleEditorDialog
from ..theme import (
    GAIN,
    GRID,
    INK_DIM,
    LOSS,
    SIZE_MICRO,
    numeric_font,
    ui_font,
)
from ..widgets.primitives import Hairline, SectionLabel

if TYPE_CHECKING:
    from ...controller import AppController

#: Wide enough for the longest label, narrow enough to stay readable.
FORM_WIDTH = 620


class StatusLine(QLabel):
    """One line that says what just happened, in green or red."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setFont(ui_font(SIZE_MICRO))
        self.setWordWrap(True)

    def say(self, message: str, *, ok: bool = True) -> None:
        self.setText(message)
        self.setStyleSheet(f"color: {GAIN if ok else LOSS};")

    def note(self, message: str) -> None:
        self.setText(message)
        self.setStyleSheet(f"color: {INK_DIM};")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class SettingsForm(QWidget):
    """The handful of settings that are a form rather than a file."""

    saved = Signal()

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        settings = controller.settings

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(GRID * 3)

        form = QFormLayout()
        form.setHorizontalSpacing(GRID * 6)
        form.setVerticalSpacing(GRID * 3)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(settings.uplink_port)
        form.addRow("Uplink port", self.port)

        self.min_comparables = QSpinBox()
        self.min_comparables.setRange(1, 50)
        self.min_comparables.setValue(settings.min_comparables)
        self.min_comparables.setToolTip(
            "Matching sales needed before a modifier is kept as a constraint"
        )
        form.addRow("Comparables needed", self.min_comparables)

        self.margin = QSpinBox()
        self.margin.setRange(0, 60)
        self.margin.setSuffix(" %")
        self.margin.setValue(int(round(settings.target_margin * 100)))
        form.addRow("Target margin", self.margin)

        self.hourly = QLineEdit(format_coins(settings.target_hourly_return))
        self.hourly.setObjectName("numericInput")
        self.hourly.setToolTip(
            "Coins one item's capital should earn per hour it is tied up.\n"
            "A per-item figure, not a target for the whole operation."
        )
        form.addRow("Return per item hour", self.hourly)

        self.exploration = QSpinBox()
        self.exploration.setRange(0, 200)
        self.exploration.setSpecialValueText("off")
        self.exploration.setValue(settings.exploration_every)
        self.exploration.setToolTip(
            "One offer in this many uses a randomised percentage.\n"
            "Without it the acceptance model only ever learns about\n"
            "the percentages you already offer."
        )
        form.addRow("Explore every", self.exploration)

        self.derpy = QCheckBox("Derpy is mayor (auction tax is doubled)")
        self.derpy.setChecked(settings.derpy)
        form.addRow("", self.derpy)

        holder = QWidget()
        holder.setLayout(form)
        # A settings field holding "5" does not need 1000px. Capping the width
        # keeps the labels near their inputs on a wide window.
        holder.setMaximumWidth(FORM_WIDTH)
        root.addWidget(holder, 0, Qt.AlignmentFlag.AlignLeft)

        self.status = StatusLine()
        buttons = QHBoxLayout()
        buttons.setSpacing(GRID * 2)
        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        buttons.addWidget(save)
        buttons.addWidget(self.status, 1)
        button_holder = QWidget()
        button_holder.setLayout(buttons)
        root.addWidget(button_holder)
        root.addStretch(1)

    def save(self) -> None:
        settings = self.controller.settings
        settings.uplink_port = int(self.port.value())
        settings.min_comparables = int(self.min_comparables.value())
        settings.target_margin = self.margin.value() / 100.0
        settings.exploration_every = int(self.exploration.value())
        settings.derpy = self.derpy.isChecked()
        try:
            settings.target_hourly_return = parse_coins(self.hourly.text())
        except ValueError:
            self.status.say("Type the hourly return as 2m or 2,000,000", ok=False)
            return

        save_settings(settings)
        # The port only takes effect on restart; everything else is read per
        # valuation, so say which is which rather than implying a live change.
        self.status.say("Saved. The uplink port applies on the next start.")
        self.saved.emit()


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

RULE_COLUMNS = ("On", "Priority", "Name", "When", "Then")
RULE_ON, RULE_PRIORITY, RULE_NAME, RULE_WHEN, RULE_THEN = range(5)


class RulesEditor(QWidget):
    """The rule list, and the buttons that change it."""

    saved = Signal()

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._rules: list[Rule] = []
        self._dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(GRID * 2)

        root.addWidget(SectionLabel("Rules"))
        blurb = QLabel(
            "Evaluated in ascending priority; for each action the first rule to"
            " set it wins. Every rule that fires is badged next to the number it"
            " produced, including one that was overridden."
        )
        blurb.setObjectName("faint")
        blurb.setFont(ui_font(SIZE_MICRO))
        blurb.setWordWrap(True)
        root.addWidget(blurb)

        self.table = QTableWidget(0, len(RULE_COLUMNS))
        self.table.setHorizontalHeaderLabels(RULE_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(
            RULE_WHEN, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            RULE_THEN, QHeaderView.ResizeMode.Stretch
        )
        self.table.itemDoubleClicked.connect(lambda _: self._edit())
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(GRID * 2)
        for label, slot, name in (
            ("New rule", self._new, "primary"),
            ("Edit", self._edit, ""),
            ("Duplicate", self._duplicate, ""),
            ("Delete", self._delete, "danger"),
        ):
            button = QPushButton(label)
            if name:
                button.setObjectName(name)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        defaults = QPushButton("Restore defaults")
        defaults.setObjectName("ghost")
        defaults.clicked.connect(self._restore_defaults)
        buttons.addWidget(defaults)
        reload_button = QPushButton("Reload from disk")
        reload_button.clicked.connect(self.reload)
        buttons.addWidget(reload_button)
        self.save_button = QPushButton("Save and apply")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        holder = QWidget()
        holder.setLayout(buttons)
        root.addWidget(holder)

        self.status = StatusLine()
        root.addWidget(self.status)

        self.reload()

    # ---- state ---------------------------------------------------------

    def reload(self) -> None:
        path = self.controller.settings.rules_file
        try:
            self._rules = load_rules(path if path.exists() else None)
        except RuleError as exc:
            # A hand-edited file that will not parse must not empty the list:
            # the user would save an empty rule set over their own work.
            self.status.say(f"Could not read {path.name}: {exc}", ok=False)
            return
        self._dirty = False
        self._render()
        self.status.note(f"{len(self._rules)} rule(s) loaded")

    def _restore_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Restore the default rules?",
            "This replaces the whole list with the rules the app ships with."
            " Nothing is written until you save.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._rules = load_rules(None)
        self._mark_dirty()
        self._render()

    def _render(self) -> None:
        self._rules.sort(key=lambda r: (r.priority, r.name))
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._rules))
        for index, rule in enumerate(self._rules):
            enabled = QTableWidgetItem()
            enabled.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            enabled.setCheckState(
                Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked
            )
            enabled.setToolTip("Turn the rule off without deleting it")
            self.table.setItem(index, RULE_ON, enabled)

            priority = QTableWidgetItem(str(rule.priority))
            priority.setFont(numeric_font(SIZE_MICRO + 2))
            self.table.setItem(index, RULE_PRIORITY, priority)

            when = " and ".join(c.describe() for c in rule.conditions) or "every item"
            cells = (rule.name, when, rule.action.describe())
            for offset, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setFont(ui_font(SIZE_MICRO + 2))
                cell.setToolTip(text)
                if not rule.enabled:
                    cell.setForeground(_dim_brush())
                self.table.setItem(index, RULE_NAME + offset, cell)
        self.table.blockSignals(False)
        self.table.resizeColumnToContents(RULE_ON)
        self.table.resizeColumnToContents(RULE_PRIORITY)
        self.table.resizeColumnToContents(RULE_NAME)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.status.note("Edited, not yet saved")

    def _selected(self) -> int:
        rows = {index.row() for index in self.table.selectedIndexes()}
        return next(iter(rows), -1) if rows else -1

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != RULE_ON:
            return
        row = item.row()
        if not (0 <= row < len(self._rules)):
            return
        from dataclasses import replace

        enabled = item.checkState() == Qt.CheckState.Checked
        self._rules[row] = replace(self._rules[row], enabled=enabled)
        self._mark_dirty()
        self._render()

    # ---- editing -------------------------------------------------------

    def _names(self, *, excluding: str | None = None) -> set[str]:
        return {r.name for r in self._rules if r.name != excluding}

    def _new(self) -> None:
        dialog = RuleEditorDialog(existing_names=self._names(), parent=self)
        if dialog.exec() and dialog.rule is not None:
            self._rules.append(dialog.rule)
            self._mark_dirty()
            self._render()

    def _edit(self) -> None:
        row = self._selected()
        if row < 0:
            self.status.say("Select a rule first", ok=False)
            return
        rule = self._rules[row]
        dialog = RuleEditorDialog(
            rule, existing_names=self._names(excluding=rule.name), parent=self
        )
        if dialog.exec() and dialog.rule is not None:
            self._rules[row] = dialog.rule
            self._mark_dirty()
            self._render()

    def _duplicate(self) -> None:
        row = self._selected()
        if row < 0:
            self.status.say("Select a rule first", ok=False)
            return
        from dataclasses import replace

        original = self._rules[row]
        name = f"{original.name} (copy)"
        suffix = 2
        while name in self._names():
            name = f"{original.name} (copy {suffix})"
            suffix += 1
        self._rules.append(replace(original, name=name))
        self._mark_dirty()
        self._render()

    def _delete(self) -> None:
        row = self._selected()
        if row < 0:
            self.status.say("Select a rule first", ok=False)
            return
        rule = self._rules[row]
        answer = QMessageBox.question(
            self,
            "Delete this rule?",
            f"{rule.name}\n\n{rule.describe()}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self._rules[row]
        self._mark_dirty()
        self._render()

    def save(self) -> None:
        path = self.controller.settings.rules_file
        try:
            text = dump_rules(self._rules)
        except Exception as exc:  # noqa: BLE001 - surface anything the dumper rejects
            self.status.say(f"{type(exc).__name__}: {exc}", ok=False)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        count = self.controller.reload_rules()
        self._dirty = False
        self.status.say(f"Saved and applied {count} rule(s)")
        self.saved.emit()

    @property
    def has_unsaved_changes(self) -> bool:
        return self._dirty


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


class PriceTable(QTableWidget):
    """A two-column name/price table where the price cell takes ``50m``."""

    def __init__(
        self,
        *,
        name_header: str = "Modifier",
        editable_names: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(0, 2, parent)
        self.editable_names = editable_names
        self.setHorizontalHeaderLabels((name_header, "Price"))
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.setAlternatingRowColors(False)

    def load(self, rows: list[tuple]) -> None:
        """``rows`` is (key, label, coins) with an optional trailing tooltip.

        The key travels with the row rather than being read back off the
        label, so a label can say more than the key does.
        """
        self.setRowCount(len(rows))
        for index, row in enumerate(rows):
            key, label, coins = row[0], row[1], row[2]
            self._set_row(index, key, label, coins, row[3] if len(row) > 3 else "")
        self.resizeRowsToContents()

    def _set_row(
        self, index: int, key: str, label: str, coins: int, tooltip: str = ""
    ) -> None:
        name = QTableWidgetItem(label)
        name.setData(Qt.ItemDataRole.UserRole, key)
        name.setFont(ui_font(SIZE_MICRO + 2))
        if tooltip:
            name.setToolTip(tooltip)
        if not self.editable_names:
            name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.setItem(index, 0, name)

        price = QTableWidgetItem(format_coins_exact(coins))
        price.setFont(numeric_font(SIZE_MICRO + 2))
        price.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        price.setToolTip("Type 50m, 1.2b or 50,000,000")
        self.setItem(index, 1, price)

    def add_row(self, key: str = "", label: str = "", coins: int = 0) -> None:
        index = self.rowCount()
        self.insertRow(index)
        self._set_row(index, key, label, coins)
        self.setCurrentCell(index, 0)
        self.editItem(self.item(index, 0))

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.selectedIndexes()}, reverse=True)
        for row in rows:
            self.removeRow(row)

    def set_price(self, key: str, coins: int) -> None:
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == key:
                self.item(row, 1).setText(format_coins_exact(coins))
                return

    def values(self) -> tuple[dict[str, int], list[str]]:
        """Every row as {key: coins}, plus the labels that would not parse."""
        out: dict[str, int] = {}
        bad: list[str] = []
        for row in range(self.rowCount()):
            name = self.item(row, 0)
            price = self.item(row, 1)
            if name is None or price is None:
                continue
            key = name.data(Qt.ItemDataRole.UserRole)
            if self.editable_names:
                key = name.text().strip().upper().replace(" ", "_")
            if not key:
                continue
            try:
                out[key] = parse_coins(price.text())
            except ValueError:
                bad.append(name.text())
        return out, bad


class PricingEditor(QWidget):
    """What every modifier is worth, and where those numbers come from."""

    saved = Signal()

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.table: ValueTable = load_values(controller.settings.values_file)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(GRID * 2)

        root.addWidget(SectionLabel("Pricing"))
        blurb = QLabel(
            "What each modifier is worth when it has to be priced on its own,"
            " and the threshold above which an enchantment is matched on rather"
            " than priced separately. An item carries twenty enchantments;"
            " insisting a comparable share all of them would leave nothing to"
            " compare against."
        )
        blurb.setObjectName("faint")
        blurb.setFont(ui_font(SIZE_MICRO))
        blurb.setWordWrap(True)
        root.addWidget(blurb)

        root.addWidget(self._bazaar_block())
        root.addWidget(self._discount_block())
        root.addWidget(Hairline())

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        self.general = self._general_form()
        tabs.addTab(_scrolled(self.general), "Thresholds")

        self.modifiers = PriceTable()
        tabs.addTab(self.modifiers, "Modifiers")
        self.ultimates = PriceTable(name_header="Ultimate enchantment")
        tabs.addTab(self.ultimates, "Ultimates")
        self.top_tier = PriceTable(name_header="Enchantment")
        tabs.addTab(self.top_tier, "Enchantments")
        tabs.addTab(self._skins_tab(), "Skins")
        root.addWidget(tabs, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(GRID * 2)
        save = QPushButton("Save and apply")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        reload_button = QPushButton("Reload from disk")
        reload_button.clicked.connect(self.reload)
        defaults = QPushButton("Restore defaults")
        defaults.setObjectName("ghost")
        defaults.clicked.connect(self._restore_defaults)
        buttons.addWidget(save)
        buttons.addWidget(reload_button)
        buttons.addWidget(defaults)
        buttons.addStretch(1)
        holder = QWidget()
        holder.setLayout(buttons)
        root.addWidget(holder)

        self.status = StatusLine()
        root.addWidget(self.status)

        controller.bazaar_prices.connect(self._on_bazaar_prices)
        self._populate()

    # ---- blocks --------------------------------------------------------

    def _bazaar_block(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GRID * 2)
        self.fetch = QPushButton("Fetch prices from the bazaar")
        self.fetch.setObjectName("primary")
        self.fetch.setToolTip(
            "One keyless request for the whole bazaar. Fills in every book,"
            " potato, master star and gemstone; leaves everything it does not"
            " trade alone."
        )
        self.fetch.clicked.connect(self._fetch_bazaar)
        self.fetch_status = StatusLine()
        row.addWidget(self.fetch)
        row.addWidget(self.fetch_status, 1)
        return holder

    def _discount_block(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, GRID, 0, 0)
        layout.setSpacing(GRID)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GRID * 3)
        label = QLabel("Deduct from every modifier price")
        label.setObjectName("dim")
        self.discount = QSlider(Qt.Orientation.Horizontal)
        self.discount.setRange(0, 100)
        self.discount.setValue(int(self.table.modifier_discount_pct))
        self.discount.setMaximumWidth(320)
        self.discount_value = QLabel()
        self.discount_value.setFont(numeric_font(SIZE_MICRO + 2))
        self.discount.valueChanged.connect(self._on_discount_changed)
        row.addWidget(label)
        row.addWidget(self.discount)
        row.addWidget(self.discount_value)
        row.addStretch(1)
        inner = QWidget()
        inner.setLayout(row)
        layout.addWidget(inner)

        note = QLabel(
            "A book on the bazaar is worth its bazaar price; the same book"
            " already applied to a sword is worth less, because nobody can take"
            " it off again. Each modifier's own recovery rate still applies on"
            " top of this."
        )
        note.setObjectName("faint")
        note.setFont(ui_font(SIZE_MICRO))
        note.setWordWrap(True)
        layout.addWidget(note)
        self._on_discount_changed(self.discount.value())
        return holder

    def _on_discount_changed(self, value: int) -> None:
        self.discount_value.setText(f"{value}%  →  {100 - value}% applied")

    def _general_form(self) -> QWidget:
        holder = QWidget()
        form = QFormLayout(holder)
        form.setHorizontalSpacing(GRID * 6)
        form.setVerticalSpacing(GRID * 3)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.min_filter = QLineEdit()
        self.min_filter.setObjectName("numericInput")
        self.min_filter.setToolTip(
            "Only enchantments worth at least this much are matched on.\n"
            "The rest are dropped and priced back separately."
        )
        form.addRow("Match on enchantments worth", self.min_filter)

        self.common_enchant = QLineEdit()
        self.common_enchant.setObjectName("numericInput")
        form.addRow("An ordinary enchantment", self.common_enchant)

        self.default_ultimate = QLineEdit()
        self.default_ultimate.setObjectName("numericInput")
        self.default_ultimate.setToolTip("Used for an ultimate not listed by name")
        form.addRow("An unlisted ultimate", self.default_ultimate)

        self.attribute_base = QLineEdit()
        self.attribute_base.setObjectName("numericInput")
        self.attribute_base.setToolTip("Level 1; each level roughly doubles it")
        form.addRow("An attribute at level 1", self.attribute_base)

        self.top_tier_level = QSpinBox()
        self.top_tier_level.setRange(1, 10)
        self.top_tier_level.setToolTip(
            "The level the enchantment prices below refer to.\n"
            "Each level under it divides the price by about six."
        )
        form.addRow("Enchantment prices are for level", self.top_tier_level)

        holder.setMaximumWidth(FORM_WIDTH)
        return holder

    def _skins_tab(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, GRID * 2, 0, 0)
        layout.setSpacing(GRID)

        note = QLabel(
            "Skins have no single price, and the bazaar does not carry them."
            " List the ones you see often, so a rule like “treat a pet skin"
            " worth under 50M as unskinned” has a real number to work from."
            " Anything not listed falls back to the generic skin value."
        )
        note.setObjectName("faint")
        note.setFont(ui_font(SIZE_MICRO))
        note.setWordWrap(True)
        layout.addWidget(note)

        self.skins = PriceTable(name_header="Skin id", editable_names=True)
        layout.addWidget(self.skins, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(GRID * 2)
        add = QPushButton("Add a skin")
        add.clicked.connect(lambda: self.skins.add_row("", "NEW_SKIN", 0))
        remove = QPushButton("Remove")
        remove.clicked.connect(self.skins.remove_selected)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        button_holder = QWidget()
        button_holder.setLayout(buttons)
        layout.addWidget(button_holder)
        return holder

    # ---- loading and saving --------------------------------------------

    def _populate(self) -> None:
        table = self.table
        self.min_filter.setText(format_coins_exact(table.min_enchant_filter_value))
        self.common_enchant.setText(format_coins_exact(table.common_enchant_value))
        self.default_ultimate.setText(format_coins_exact(table.default_ultimate_value))
        self.attribute_base.setText(format_coins_exact(table.attribute_base))
        self.top_tier_level.setValue(int(table.top_tier_level))
        self.discount.setValue(int(table.modifier_discount_pct))

        rows: list[tuple[str, str, int]] = [
            ("recomb", "Recombobulator 3000", table.recomb),
            ("art_of_war", "The Art of War", table.art_of_war),
            ("reforge", "A reforge", table.reforge),
            ("rune", "A rune", table.rune),
            ("skin", "A skin (generic)", table.skin),
            ("dye", "A dye", table.dye),
            ("hot_potato", "Hot potato book", table.hot_potato),
            ("fuming_potato", "Fuming potato book", table.fuming_potato),
            ("pet_held_item", "A pet held item", table.pet_held_item),
            ("ability_scroll", "An ability scroll", table.ability_scroll),
            ("essence_star", "An essence star", table.essence_star),
        ]
        rows += [
            (f"gem:{quality}", f"{quality.title()} gemstone", price)
            for quality, price in table.gems.items()
        ]
        rows += [
            (f"star:{index}", f"Master star {index + 1}", price)
            for index, price in enumerate(table.master_stars)
        ]
        self.modifiers.load(rows)

        self.ultimates.load(
            [
                (name, name.replace("ultimate_", "").replace("_", " ").title(), price)
                for name, price in sorted(table.ultimate_enchants.items())
            ]
        )
        # The level a price refers to is as important as the price: read as
        # level VII, a Looting V price would value every Looting book on every
        # item at a fraction of what it is worth.
        self.top_tier.load(
            [
                (
                    name,
                    f"{name.replace('_', ' ').title()}  ·  level"
                    f" {table.reference_level(name)}",
                    price,
                    f"The price of one at level {table.reference_level(name)}."
                    f" Each level below is worth {table.decay_for(name):.0f}x less"
                    + (
                        " (measured from the bazaar)."
                        if name in table.top_tier_decay
                        else ", which is an assumption until you fetch prices."
                    ),
                )
                for name, price in sorted(table.top_tier_enchants.items())
            ]
        )
        self.skins.load(
            [(name, name, price) for name, price in sorted(table.skin_values.items())]
        )

    def _collect(self) -> ValueTable | None:
        """Read every widget back into a table, or say what would not parse."""
        table = ValueTable()
        bad: list[str] = []

        def coins(field: QLineEdit, label: str) -> int:
            try:
                return parse_coins(field.text())
            except ValueError:
                bad.append(label)
                return 0

        table.min_enchant_filter_value = coins(self.min_filter, "the matching threshold")
        table.common_enchant_value = coins(self.common_enchant, "an ordinary enchantment")
        table.default_ultimate_value = coins(self.default_ultimate, "an unlisted ultimate")
        table.attribute_base = coins(self.attribute_base, "an attribute at level 1")
        table.top_tier_level = int(self.top_tier_level.value())
        table.modifier_discount_pct = int(self.discount.value())

        modifiers, unparsed = self.modifiers.values()
        bad += unparsed
        gems: dict[str, int] = {}
        stars: dict[int, int] = {}
        for key, value in modifiers.items():
            if key.startswith("gem:"):
                gems[key.split(":", 1)[1]] = value
            elif key.startswith("star:"):
                stars[int(key.split(":", 1)[1])] = value
            elif hasattr(table, key):
                setattr(table, key, value)
        if gems:
            table.gems = gems
        if stars:
            table.master_stars = [stars[i] for i in sorted(stars)]

        ultimates, unparsed = self.ultimates.values()
        bad += unparsed
        table.ultimate_enchants = {k.lower(): v for k, v in ultimates.items()}

        top_tier, unparsed = self.top_tier.values()
        bad += unparsed
        table.top_tier_enchants = {k.lower(): v for k, v in top_tier.items()}
        # Levels and decay are not editable here; they are carried across from
        # whatever the last fetch measured rather than reset to the defaults.
        table.top_tier_levels = dict(self.table.top_tier_levels)
        table.top_tier_decay = dict(self.table.top_tier_decay)

        skins, unparsed = self.skins.values()
        bad += unparsed
        table.skin_values = skins

        if bad:
            shown = ", ".join(bad[:4]) + ("…" if len(bad) > 4 else "")
            self.status.say(
                f"Could not read {len(bad)} price(s): {shown}."
                " Type them as 50m, 1.2b or 50,000,000.",
                ok=False,
            )
            return None
        return table

    def reload(self) -> None:
        self.table = load_values(self.controller.settings.values_file)
        self._populate()
        self.status.note("Reloaded from disk")

    def _restore_defaults(self) -> None:
        self.table = ValueTable()
        self._populate()
        self.status.note("Defaults loaded, not yet saved")

    def save(self) -> None:
        table = self._collect()
        if table is None:
            return
        self.table = table
        save_values(table, self.controller.settings.values_file)
        applied = self.controller.reload_values()
        self.status.say(
            "Saved and applied. Matching on enchantments worth "
            f"{format_coins(applied.min_enchant_filter_value)} or more,"
            f" modifiers at {100 - applied.modifier_discount_pct}% of their price."
        )
        self.saved.emit()

    # ---- the bazaar ----------------------------------------------------

    def _fetch_bazaar(self) -> None:
        self.fetch.setEnabled(False)
        self.fetch_status.note("Asking the bazaar…")
        self.controller.fetch_bazaar_prices()

    def _on_bazaar_prices(self, result: Any) -> None:
        self.fetch.setEnabled(True)
        if isinstance(result, Exception):
            self.fetch_status.say(f"Could not reach the bazaar: {result}", ok=False)
            return
        # Applied to what is on screen, not to what is on disk: an edit made
        # thirty seconds ago should survive a price fetch.
        table = self._collect()
        if table is None:
            self.fetch_status.say("Fix the prices flagged below first", ok=False)
            return
        refresh = refresh_values(table, result)
        self.table = table
        self._populate()
        self.fetch_status.say(
            f"{refresh.summary()}. Nothing saved yet."
            f" Not traded there: {', '.join(NOT_ON_BAZAAR[:4])}…"
        )


# ---------------------------------------------------------------------------


class ConfigView(QWidget):
    """Settings, rules and pricing, in that order of how often they change."""

    settings_saved = Signal()
    rules_saved = Signal()
    values_saved = Signal()

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller

        root = QVBoxLayout(self)
        root.setContentsMargins(GRID * 7, GRID * 6, GRID * 7, GRID * 6)
        root.setSpacing(GRID * 4)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        self.settings_form = SettingsForm(controller)
        self.settings_form.saved.connect(self.settings_saved.emit)
        tabs.addTab(_scrolled(self.settings_form), "Settings")

        self.rules_editor = RulesEditor(controller)
        self.rules_editor.saved.connect(self.rules_saved.emit)
        tabs.addTab(self.rules_editor, "Rules")

        self.values_editor = PricingEditor(controller)
        self.values_editor.saved.connect(self.values_saved.emit)
        tabs.addTab(self.values_editor, "Pricing")

        root.addWidget(tabs, 1)

        where = QLabel(f"Files live in {controller.settings.data_dir}")
        where.setObjectName("faint")
        where.setFont(ui_font(SIZE_MICRO))
        where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(where)


def _dim_brush():
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(INK_DIM))


def _scrolled(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(0, GRID * 3, 0, 0)
    layout.addWidget(widget)
    layout.addStretch(1)
    area.setWidget(inner)
    return area
