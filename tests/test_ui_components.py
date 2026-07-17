from maclean.ui_components import TableModel, TableRow


def test_table_model_only_checks_selectable_rows():
    model = TableModel[str]()
    model.set_rows(
        [
            TableRow("a", ("A",), "payload-a", selectable=True),
            TableRow("b", ("B",), "payload-b", selectable=False),
        ]
    )

    assert model.toggle("a") is True
    assert model.toggle("b") is False
    assert model.checked_payloads() == ["payload-a"]


def test_table_model_preserves_input_order_for_checked_payloads():
    model = TableModel[int]()
    model.set_rows(
        [
            TableRow("a", ("A",), 1, checked=True),
            TableRow("b", ("B",), 2),
            TableRow("c", ("C",), 3, checked=True),
        ]
    )

    assert model.checked_payloads() == [1, 3]


def test_set_all_checks_only_selectable_rows():
    model = TableModel[str]()
    model.set_rows(
        [
            TableRow("a", ("A",), "a", selectable=True),
            TableRow("b", ("B",), "b", selectable=False),
            TableRow("c", ("C",), "c", selectable=True),
        ]
    )

    model.set_all(True)

    assert model.checked_payloads() == ["a", "c"]  # korumalı 'b' işaretlenmez

    model.set_all(False)

    assert model.checked_payloads() == []


def test_set_all_scoped_to_given_iids():
    """Filtre dışı satırlar (verilmeyen iid'ler) etkilenmemeli."""
    model = TableModel[str]()
    model.set_rows(
        [
            TableRow("a", ("A",), "a", selectable=True),
            TableRow("b", ("B",), "b", selectable=True),
        ]
    )

    model.set_all(True, iids=["a"])

    assert model.checked_payloads() == ["a"]
