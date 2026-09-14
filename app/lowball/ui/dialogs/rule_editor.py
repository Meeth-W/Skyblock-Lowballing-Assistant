"""Building one rule, without typing YAML.

Every control here is generated from :mod:`lowball.rules.catalogue`, so the
menus can only offer conditions the engine actually evaluates and actions it
actually performs. Writing rules by hand meant a typo produced a rule that
parsed, loaded, and silently never fired -- the worst possible failure for
something whose whole job is to stop you overpaying.

A condition is three controls: a field, an operator, and a value editor whose
type follows the field. Picking "Pet skin value" offers coin comparisons and a
coin field; picking "Is a pet" offers yes and no and nothing else.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...money import format_coins, format_coins_exact, parse_coins
from ...rules.catalogue import (
    ACTIONS_BY_KEY,
    BOOLEAN,
    CHOICE,
    COINS,
    FIELD_GROUPS,
    FIELDS,
    MAP,
    NORMALISATIONS,
    NORMALISATIONS_BY_KEY,
    NUMBER,
    OPERATOR_LABELS,
    TEXT,
    FieldSpec,
    field_spec,
)
from ...rules.model import Action, Condition, Rule, RuleError
from ..theme import (
    GRID,
    LOSS,
    SIZE_MICRO,
    SIZE_SECTION,
    WEIGHT_EMPHASIS,
    stylesheet,
    ui_font,
)
from ..widgets.primitives import Hairline, SectionLabel

#: Fields with no spec -- ``enchant:sharpness`` and the like -- still have to
#: be editable, so an unrecognised one is shown as free text.
FREE_TEXT = FieldSpec("", "", TEXT, "")


def _contain(box: QComboBox, characters: int) -> None:
    """Stop a combo sizing itself to its longest entry.

    Left alone, a list of forty field names drags the dialog wider than the
    window and every value editor ends up off the right-hand edge.
    """
    box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    box.setMinimumContentsLength(characters)
    box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)


class CoinEdit(QLineEdit):
    """A coin field that accepts 50m and reports 50,000,000."""

    def __init__(self, coins: int | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("numericInput")
        self.setPlaceholderText("e.g. 50m")
        if coins is not None:
            self.set_coins(coins)

    def set_coins(self, coins: int) -> None:
        self.setText(format_coins_exact(coins))
        self.setToolTip(format_coins(coins))

    def coins(self) -> int | None:
        text = self.text().strip()
        if not text:
            return None
        try:
            return parse_coins(text)
        except ValueError:
            return None


def _value_editor(spec: FieldSpec, value: Any = None) -> QWidget:
    """The right control for a field's kind, pre-filled."""
    if spec.kind == BOOLEAN:
        box = QComboBox()
        box.addItems(["yes", "no"])
        box.setCurrentIndex(0 if value is None or bool(value) else 1)
        return box
    if spec.kind == CHOICE:
        box = QComboBox()
        box.setEditable(True)
        box.addItems(list(spec.choices))
        box.setCurrentText("" if value is None else str(value))
        return box
    if spec.kind == COINS:
        return CoinEdit(int(value) if value is not None else None)
    if spec.kind == NUMBER:
        spin = QDoubleSpinBox()
        spin.setRange(-1_000_000_000, 1_000_000_000)
        spin.setDecimals(0)
        spin.setValue(float(value) if value is not None else 0.0)
        return spin
    line = QLineEdit("" if value is None else str(value))
    if spec.kind == MAP:
        line.setPlaceholderText("enchantment name, e.g. ultimate_wise")
    return line


def _editor_value(spec: FieldSpec, widget: QWidget) -> Any:
    if spec.kind == BOOLEAN:
        return widget.currentText() == "yes"
    if spec.kind == CHOICE:
        return widget.currentText().strip()
    if spec.kind == COINS:
        return widget.coins()
    if spec.kind == NUMBER:
        return int(widget.value())
    return widget.text().strip()


class ConditionRow(QWidget):
    """One line of the "when" list."""

    def __init__(
        self, condition: Condition | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GRID * 2)

        self.field = QComboBox()
        _contain(self.field, 22)
        for group in FIELD_GROUPS:
            for spec in FIELDS:
                if spec.group != group:
                    continue
                label = spec.label if spec.kind != BOOLEAN else f"Is {spec.label}"
                self.field.addItem(f"{group}: {label}", spec.name)
                if spec.help:
                    index = self.field.count() - 1
                    self.field.setItemData(index, spec.help, Qt.ItemDataRole.ToolTipRole)

        self.operator = QComboBox()
        _contain(self.operator, 14)

        self.value_holder = QWidget()
        self.value_layout = QHBoxLayout(self.value_holder)
        self.value_layout.setContentsMargins(0, 0, 0, 0)
        self.value_editor: QWidget = QLineEdit()

        remove = QPushButton("✕")
        remove.setObjectName("ghost")
        remove.setFixedWidth(28)
        remove.setToolTip("Remove this condition")
        remove.clicked.connect(self._remove)

        row.addWidget(self.field)
        row.addWidget(self.operator)
        row.addWidget(self.value_holder, 1)
        row.addWidget(remove)

        self.field.currentIndexChanged.connect(lambda _i: self._on_field_changed())

        if condition is not None:
            index = self.field.findData(condition.field)
            if index >= 0:
                self.field.setCurrentIndex(index)
            else:
                # A hand-written field such as enchant:sharpness. Keep it
                # rather than dropping it on the floor when the rule is saved.
                self.field.addItem(condition.field, condition.field)
                self.field.setCurrentIndex(self.field.count() - 1)
            self._on_field_changed(condition.op, condition.expected)
        else:
            self._on_field_changed()

    # ---- wiring --------------------------------------------------------

    @property
    def spec(self) -> FieldSpec:
        return field_spec(self.field.currentData()) or FREE_TEXT

    def _on_field_changed(self, op: str | None = None, value: Any = None) -> None:
        spec = self.spec
        self.operator.blockSignals(True)
        self.operator.clear()
        for operator in spec.operators:
            self.operator.addItem(OPERATOR_LABELS.get(operator, operator), operator)
        if op:
            index = self.operator.findData(op)
            if index < 0:
                self.operator.addItem(OPERATOR_LABELS.get(op, op), op)
                index = self.operator.count() - 1
            self.operator.setCurrentIndex(index)
        self.operator.blockSignals(False)
        # Boolean fields read as "is a pet" / "is not a pet", so their value
        # editor is the only place yes and no belong.
        self.operator.setVisible(spec.kind != BOOLEAN)

        while self.value_layout.count():
            item = self.value_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.value_editor = _value_editor(spec, value)
        self.value_layout.addWidget(self.value_editor)
        self.value_editor.setVisible(self.operator.currentData() != "exists")

    def _remove(self) -> None:
        self.setParent(None)
        self.deleteLater()

    def condition(self) -> Condition | None:
        spec = self.spec
        name = self.field.currentData()
        if not name:
            return None
        if spec.kind == BOOLEAN:
            return Condition(name, "eq", _editor_value(spec, self.value_editor))
        op = self.operator.currentData()
        if op == "exists":
            return Condition(name, "exists", True)
        value = _editor_value(spec, self.value_editor)
        if value in (None, ""):
            return None
        if op in {"in", "not_in"} and isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        return Condition(name, op, value)


class NormaliseRow(QWidget):
    """One line of the "rewrite the item" list."""

    def __init__(
        self, key: str | None = None, value: Any = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GRID * 2)

        self.key = QComboBox()
        _contain(self.key, 26)
        for spec in NORMALISATIONS:
            self.key.addItem(spec.label, spec.key)
            if spec.help:
                self.key.setItemData(
                    self.key.count() - 1, spec.help, Qt.ItemDataRole.ToolTipRole
                )

        self.value_holder = QWidget()
        self.value_layout = QHBoxLayout(self.value_holder)
        self.value_layout.setContentsMargins(0, 0, 0, 0)
        self.value_editor: QWidget = QLineEdit()

        remove = QPushButton("✕")
        remove.setObjectName("ghost")
        remove.setFixedWidth(28)
        remove.clicked.connect(self._remove)

        row.addWidget(self.key)
        row.addWidget(self.value_holder, 1)
        row.addWidget(remove)

        self.key.currentIndexChanged.connect(lambda _i: self._rebuild())
        if key:
            index = self.key.findData(key)
            if index >= 0:
                self.key.setCurrentIndex(index)
        self._rebuild(value)

    def _rebuild(self, value: Any = None) -> None:
        spec = NORMALISATIONS_BY_KEY[self.key.currentData()]
        while self.value_layout.count():
            item = self.value_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        shown = value if value is not None else spec.default
        as_field = FieldSpec(spec.key, spec.label, spec.kind, "", spec.choices)
        self.value_editor = _value_editor(as_field, shown)
        self.value_layout.addWidget(self.value_editor)
        # "Ignore every gemstone" takes no argument: it either applies or the
        # row is not there.
        self.value_editor.setVisible(spec.key != "gems")

    def _remove(self) -> None:
        self.setParent(None)
        self.deleteLater()

    def entry(self) -> tuple[str, Any] | None:
        spec = NORMALISATIONS_BY_KEY[self.key.currentData()]
        if spec.key == "gems":
            return spec.key, True
        as_field = FieldSpec(spec.key, spec.label, spec.kind, "", spec.choices)
        value = _editor_value(as_field, self.value_editor)
        if value in (None, ""):
            return None
        return spec.key, value


class RuleEditorDialog(QDialog):
    """Create or edit one rule."""

    def __init__(
        self,
        rule: Rule | None = None,
        *,
        existing_names: set[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.rule: Rule | None = None
        self._original_name = rule.name if rule else None
        self._taken = {n for n in (existing_names or set())}
        self.setWindowTitle("Edit rule" if rule else "New rule")
        self.setStyleSheet(stylesheet())
        self.setMinimumWidth(720)
        self.resize(760, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(GRID * 6, GRID * 5, GRID * 6, GRID * 5)
        root.setSpacing(GRID * 2)

        heading = QLabel("Edit rule" if rule else "New rule")
        heading.setFont(ui_font(SIZE_SECTION, WEIGHT_EMPHASIS))
        root.addWidget(heading)

        head = QFormLayout()
        head.setHorizontalSpacing(GRID * 4)
        head.setVerticalSpacing(GRID * 2)
        self.name = QLineEdit(rule.name if rule else "")
        self.name.setPlaceholderText("What this rule is for")
        head.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        head.addRow("Name", self.name)
        self.priority = QSpinBox()
        self.priority.setFixedWidth(110)
        self.priority.setRange(1, 999)
        self.priority.setValue(rule.priority if rule else 100)
        self.priority.setToolTip(
            "Lower runs first, and the first rule to set an action wins it."
        )
        head.addRow("Priority", self.priority)
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(rule.enabled if rule else True)
        head.addRow("", self.enabled)
        head_holder = QWidget()
        head_holder.setLayout(head)
        root.addWidget(head_holder)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(GRID * 3)

        body_layout.addWidget(self._conditions_block(rule))
        body_layout.addWidget(self._actions_block(rule))
        body_layout.addWidget(self._normalise_block(rule))
        body_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.error = QLabel("")
        self.error.setFont(ui_font(SIZE_MICRO))
        self.error.setStyleSheet(f"color: {LOSS};")
        self.error.setWordWrap(True)
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save rule")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        button_holder = QWidget()
        button_holder.setLayout(buttons)
        root.addWidget(button_holder)

    # ---- blocks --------------------------------------------------------

    def _conditions_block(self, rule: Rule | None) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GRID)
        layout.addWidget(SectionLabel("When all of these hold"))
        layout.addWidget(Hairline())

        self.conditions = QVBoxLayout()
        self.conditions.setContentsMargins(0, 0, 0, 0)
        self.conditions.setSpacing(GRID)
        layout.addLayout(self.conditions)

        add = QPushButton("Add a condition")
        add.clicked.connect(lambda: self._add_condition())
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)

        note = QLabel(
            "No conditions means the rule fires on every item, which is"
            " occasionally what you want and usually not."
        )
        note.setObjectName("faint")
        note.setFont(ui_font(SIZE_MICRO))
        note.setWordWrap(True)
        layout.addWidget(note)

        for condition in rule.conditions if rule else []:
            self._add_condition(condition)
        return holder

    def _add_condition(self, condition: Condition | None = None) -> None:
        self.conditions.addWidget(ConditionRow(condition))

    def _actions_block(self, rule: Rule | None) -> QWidget:
        action = rule.action if rule else Action()
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GRID)
        layout.addWidget(SectionLabel("Then"))
        layout.addWidget(Hairline())

        form = QFormLayout()
        form.setHorizontalSpacing(GRID * 4)
        form.setVerticalSpacing(GRID * 2)

        self.use_offer = QCheckBox(ACTIONS_BY_KEY["offer_pct"].label)
        self.offer_pct = QDoubleSpinBox()
        self.offer_pct.setFixedWidth(110)
        self.offer_pct.setRange(0.0, 95.0)
        self.offer_pct.setDecimals(0)
        self.offer_pct.setSuffix(" %")
        self.offer_pct.setValue(
            round((action.offer_pct or 0.0) * 100) if action.offer_pct else 20
        )
        self.use_offer.setChecked(action.offer_pct is not None)
        self.offer_pct.setEnabled(self.use_offer.isChecked())
        self.use_offer.toggled.connect(self.offer_pct.setEnabled)
        form.addRow(self.use_offer, self.offer_pct)

        self.use_cap = QCheckBox(ACTIONS_BY_KEY["max_coins"].label)
        self.max_coins = CoinEdit(action.max_coins)
        self.max_coins.setFixedWidth(160)
        self.use_cap.setChecked(action.max_coins is not None)
        self.max_coins.setEnabled(self.use_cap.isChecked())
        self.use_cap.toggled.connect(self.max_coins.setEnabled)
        form.addRow(self.use_cap, self.max_coins)

        self.exclude = QCheckBox(ACTIONS_BY_KEY["exclude"].label)
        self.exclude.setChecked(action.exclude)
        self.exclude.setToolTip(ACTIONS_BY_KEY["exclude"].help)
        form.addRow("", self.exclude)

        self.valuation = QComboBox()
        _contain(self.valuation, 16)
        self.valuation.addItem("default", "")
        for choice in ACTIONS_BY_KEY["valuation"].choices:
            self.valuation.addItem(choice, choice)
        index = self.valuation.findData(action.valuation or "")
        self.valuation.setCurrentIndex(max(0, index))
        form.addRow(ACTIONS_BY_KEY["valuation"].label, self.valuation)

        self.note = QLineEdit(action.note or "")
        self.note.setMinimumWidth(360)
        self.note.setPlaceholderText("Shown beside the badge on the estimate")
        form.addRow(ACTIONS_BY_KEY["note"].label, self.note)

        self.stop = QCheckBox(ACTIONS_BY_KEY["stop"].label)
        self.stop.setChecked(action.stop)
        self.stop.setToolTip(ACTIONS_BY_KEY["stop"].help)
        form.addRow("", self.stop)

        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
        )
        form_holder = QWidget()
        form_holder.setLayout(form)
        layout.addWidget(form_holder)
        return holder

    def _normalise_block(self, rule: Rule | None) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GRID)
        layout.addWidget(SectionLabel("And rewrite the item before valuing it"))
        layout.addWidget(Hairline())

        blurb = QLabel(
            "The strongest thing a rule can do: it changes which comparables"
            " are searched for, not just the number that comes out."
        )
        blurb.setObjectName("faint")
        blurb.setFont(ui_font(SIZE_MICRO))
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        self.normalisations = QVBoxLayout()
        self.normalisations.setContentsMargins(0, 0, 0, 0)
        self.normalisations.setSpacing(GRID)
        layout.addLayout(self.normalisations)

        add = QPushButton("Add a rewrite")
        add.clicked.connect(lambda: self.normalisations.addWidget(NormaliseRow()))
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)

        for key, value in (rule.action.normalise if rule else {}).items():
            if key in NORMALISATIONS_BY_KEY:
                self.normalisations.addWidget(NormaliseRow(key, value))
        return holder

    # ---- saving --------------------------------------------------------

    def _rows(self, layout: QVBoxLayout) -> list[QWidget]:
        return [
            layout.itemAt(i).widget()
            for i in range(layout.count())
            if layout.itemAt(i).widget() is not None
        ]

    def _on_save(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.error.setText("Every rule needs a name; it is what gets badged.")
            self.name.setFocus()
            return
        if name != self._original_name and name in self._taken:
            self.error.setText(f"There is already a rule called {name!r}.")
            self.name.setFocus()
            return

        conditions = [
            condition
            for condition in (row.condition() for row in self._rows(self.conditions))
            if condition is not None
        ]
        normalise: dict[str, Any] = {}
        for row in self._rows(self.normalisations):
            entry = row.entry()
            if entry is not None:
                normalise[entry[0]] = entry[1]

        then: dict[str, Any] = {}
        if self.use_offer.isChecked():
            then["offer_pct"] = self.offer_pct.value()
        if self.use_cap.isChecked():
            coins = self.max_coins.coins()
            if coins is None:
                self.error.setText("Type the cap as 50m or 50,000,000.")
                return
            then["max_coins"] = coins
        if self.exclude.isChecked():
            then["exclude"] = True
        if self.valuation.currentData():
            then["valuation"] = self.valuation.currentData()
        if self.note.text().strip():
            then["note"] = self.note.text().strip()
        if self.stop.isChecked():
            then["stop"] = True
        if normalise:
            then["normalise"] = normalise

        if not then:
            self.error.setText("A rule that does nothing will never tell you anything.")
            return

        try:
            action = Action.parse(then, name)
        except RuleError as exc:
            self.error.setText(str(exc))
            return

        self.rule = Rule(
            name=name,
            priority=int(self.priority.value()),
            conditions=conditions,
            action=action,
            enabled=self.enabled.isChecked(),
        )
        self.accept()
