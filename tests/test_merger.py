import lxml.etree as ET
import pytest
from unittest.mock import patch

from pycobertura.merger import CoberturaMerger


@pytest.fixture
def make_file(tmp_path):
    def _make_file(filename, content):
        f = tmp_path / filename
        f.write_text(content)
        return str(f)

    return _make_file


def test_merger_init_no_files():
    """Test that CoberturaMerger raises ValueError when no files are provided."""
    with pytest.raises(ValueError, match="At least one Cobertura file is required."):
        CoberturaMerger([])


def test_simple_merge_line_hits(make_file):
    """Test that line hits are summed correctly."""
    xml1 = """<?xml version="1.0" ?>
<coverage line-rate="0.5"><packages><package name="foo" line-rate="0.5"><classes>
    <class name="bar" filename="foo/bar.py" line-rate="0.5">
        <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
        </lines>
    </class>
</classes></package></packages></coverage>"""
    xml2 = """<?xml version="1.0" ?>
<coverage line-rate="1.0"><packages><package name="foo" line-rate="1.0"><classes>
    <class name="bar" filename="foo/bar.py" line-rate="1.0">
        <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
        </lines>
    </class>
</classes></package></packages></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    f2 = make_file("coverage2.xml", xml2)

    merger = CoberturaMerger([f1, f2])
    merged_report = merger.merge()
    root = ET.fromstring(merged_report)

    line1 = root.xpath('.//line[@number="1"]')[0]
    assert line1.get("hits") == "2"  # 1 + 1
    line2 = root.xpath('.//line[@number="2"]')[0]
    assert line2.get("hits") == "1"  # 0 + 1

    # All lines are now hit (2/2)
    assert root.get("line-rate") == "1.0"
    assert root.xpath('.//class[@name="bar"]')[0].get("line-rate") == "1.0"
    assert root.xpath('.//package[@name="foo"]')[0].get("line-rate") == "1.0"


def test_merge_branch_coverage(make_file):
    """Test optimistic merging of branch coverage."""
    xml1 = """<?xml version="1.0" ?>
<coverage branch-rate="0.25"><packages><package name="foo" branch-rate="0.25"><classes>
    <class name="bar" filename="foo/bar.py" branch-rate="0.25">
        <lines>
            <line number="1" hits="1" branch="true" condition-coverage="25% (1/4)">
                <conditions><condition number="0" type="jump" coverage="25%"/></conditions>
            </line>
        </lines>
    </class>
</classes></package></packages></coverage>"""
    xml2 = """<?xml version="1.0" ?>
<coverage branch-rate="0.75"><packages><package name="foo" branch-rate="0.75"><classes>
    <class name="bar" filename="foo/bar.py" branch-rate="0.75">
        <lines>
            <line number="1" hits="1" branch="true" condition-coverage="75% (3/4)">
                <conditions><condition number="0" type="jump" coverage="75%"/></conditions>
            </line>
        </lines>
    </class>
</classes></package></packages></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    f2 = make_file("coverage2.xml", xml2)

    merger = CoberturaMerger([f1, f2])
    merged_report = merger.merge()
    root = ET.fromstring(merged_report)

    line1 = root.xpath('.//line[@number="1"]')[0]
    assert line1.get("condition-coverage") == "75% (3/4)"
    assert root.get("branch-rate") == "0.75"
    assert root.xpath('.//class[@name="bar"]')[0].get("branch-rate") == "0.75"


def test_merge_new_class(make_file):
    """Test merging a report with a new class."""
    xml1 = """<?xml version="1.0" ?>
<coverage line-rate="1.0"><packages><package name="foo" line-rate="1.0"><classes>
    <class name="bar" filename="foo/bar.py" line-rate="1.0">
        <lines><line number="1" hits="1"/></lines>
    </class>
</classes></package></packages></coverage>"""
    xml2 = """<?xml version="1.0" ?>
<coverage line-rate="0.0"><packages><package name="foo" line-rate="0.0"><classes>
    <class name="baz" filename="foo/baz.py" line-rate="0.0">
        <lines><line number="1" hits="0"/></lines>
    </class>
</classes></package></packages></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    f2 = make_file("coverage2.xml", xml2)

    merger = CoberturaMerger([f1, f2])
    merged_report = merger.merge()
    root = ET.fromstring(merged_report)

    assert len(root.xpath('.//class')) == 2
    assert root.xpath('.//class[@name="baz"]')
    # 1 of 2 lines covered
    assert root.get("line-rate") == "0.5"
    assert root.xpath('.//package[@name="foo"]')[0].get("line-rate") == "0.5"


def test_merge_new_package(make_file):
    """Test merging a report with a new package."""
    xml1 = """<?xml version="1.0" ?>
<coverage line-rate="1.0"><packages><package name="foo" line-rate="1.0"><classes>
    <class name="bar" filename="foo/bar.py" line-rate="1.0">
        <lines><line number="1" hits="1"/></lines>
    </class>
</classes></package></packages></coverage>"""
    xml2 = """<?xml version="1.0" ?>
<coverage line-rate="0.0"><packages><package name="bar" line-rate="0.0"><classes>
    <class name="baz" filename="bar/baz.py" line-rate="0.0">
        <lines><line number="1" hits="0"/></lines>
    </class>
</classes></package></packages></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    f2 = make_file("coverage2.xml", xml2)

    merger = CoberturaMerger([f1, f2])
    merged_report = merger.merge()
    root = ET.fromstring(merged_report)

    assert len(root.xpath('packages/package')) == 2
    assert root.xpath('packages/package[@name="bar"]')
    # 1 of 2 lines covered
    assert root.get("line-rate") == "0.5"


def test_merge_sources(make_file):
    """Test that <sources> are merged without duplicates."""
    xml1 = """<?xml version="1.0" ?>
<coverage><sources><source>/src</source></sources><packages/></coverage>"""
    xml2 = """<?xml version="1.0" ?>
<coverage><sources><source>/src</source><source>/test</source></sources><packages/></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    f2 = make_file("coverage2.xml", xml2)

    merger = CoberturaMerger([f1, f2])
    merged_report = merger.merge()
    root = ET.fromstring(merged_report)

    sources = root.xpath('sources/source')
    assert len(sources) == 2
    source_texts = {s.text for s in sources}
    assert source_texts == {"/src", "/test"}


def test_merge_no_sources_element(make_file):
    """Test merging when the base report has no <sources> element."""
    xml1 = """<?xml version="1.0" ?>
<coverage><packages/></coverage>"""
    xml2 = """<?xml version="1.0" ?>
<coverage><sources><source>/src</source></sources><packages/></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    f2 = make_file("coverage2.xml", xml2)

    merger = CoberturaMerger([f1, f2])
    merged_report = merger.merge()
    root = ET.fromstring(merged_report)

    sources = root.xpath('sources/source')
    assert len(sources) == 1
    assert sources[0].text == "/src"


def test_merge_new_line_in_class(make_file):
    """Test merging when a class has a new line."""
    xml1 = """<?xml version="1.0" ?>
<coverage line-rate="1.0"><packages><package name="foo" line-rate="1.0"><classes>
    <class name="bar" filename="foo/bar.py" line-rate="1.0">
        <lines><line number="1" hits="1"/></lines>
    </class>
</classes></package></packages></coverage>"""
    xml2 = """<?xml version="1.0" ?>
<coverage line-rate="0.5"><packages><package name="foo" line-rate="0.5"><classes>
    <class name="bar" filename="foo/bar.py" line-rate="0.5">
        <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
        </lines>
    </class>
</classes></package></packages></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    f2 = make_file("coverage2.xml", xml2)

    merger = CoberturaMerger([f1, f2])
    merged_report = merger.merge()
    root = ET.fromstring(merged_report)

    lines = root.xpath('.//class[@name="bar"]/lines/line')
    assert len(lines) == 2
    assert root.get("line-rate") == "0.5"  # 1 of 2 lines covered


def test_update_timestamp(make_file):
    xml1 = """<?xml version="1.0" ?><coverage timestamp="12345"><packages/></coverage>"""
    xml2 = """<?xml version="1.0" ?><coverage timestamp="67890"><packages/></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    f2 = make_file("coverage2.xml", xml2)

    with patch('pycobertura.merger.datetime') as mock_datetime:
        mock_datetime.now.return_value.timestamp.return_value = 1672574400
        merger = CoberturaMerger([f1, f2])
        merged_report = merger.merge()
        root = ET.fromstring(merged_report)
        assert root.get("timestamp") == "1672574400"


def test_merge_with_empty_elements(make_file):
    """Test merging reports with various empty or missing elements."""
    xml1 = """<?xml version="1.0" ?>
<coverage><packages><package name="p1"><classes>
    <class name="c1" filename="f1.py">
        <lines/>
    </class>
    <class name="c2" filename="f2.py"/>
</classes></package></packages></coverage>"""
    xml2 = """<?xml version="1.0" ?>
<coverage><packages><package name="p1"><classes>
    <class name="c1" filename="f1.py">
        <lines><line number="1" hits="1"/></lines>
    </class>
    <class name="c3" filename="f3.py">
        <lines><line number="1" hits="0"/></lines>
    </class>
</classes></package><package name="p2"/></packages></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    f2 = make_file("coverage2.xml", xml2)

    merger = CoberturaMerger([f1, f2])
    merged_report = merger.merge()
    root = ET.fromstring(merged_report)

    assert root.xpath('.//class[@filename="f1.py"]/lines/line[@number="1"]')
    assert root.xpath('.//class[@filename="f2.py"]')
    assert root.xpath('.//class[@filename="f3.py"]')
    assert root.xpath('.//package[@name="p2"]')

    # 1 of 2 lines covered
    assert root.get("line-rate") == "0.5"


def test_merge_three_files(make_file):
    """Test merging three files."""
    xml1 = """<?xml version="1.0" ?><coverage><packages><package name="p"><classes>
    <class name="c" filename="f.py"><lines><line number="1" hits="1"/></lines></class>
</classes></package></packages></coverage>"""
    xml2 = """<?xml version="1.0" ?><coverage><packages><package name="p"><classes>
    <class name="c" filename="f.py"><lines><line number="1" hits="1"/></lines></class>
</classes></package></packages></coverage>"""
    xml3 = """<?xml version="1.0" ?><coverage><packages><package name="p"><classes>
    <class name="c" filename="f.py"><lines><line number="1" hits="1"/></lines></class>
</classes></package></packages></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    f2 = make_file("coverage2.xml", xml2)
    f3 = make_file("coverage3.xml", xml3)

    merger = CoberturaMerger([f1, f2, f3])
    merged_report = merger.merge()
    root = ET.fromstring(merged_report)

    line1 = root.xpath('.//line[@number="1"]')[0]
    assert line1.get("hits") == "3"


def test_merge_output_is_bytes(make_file):
    """Test that the output of merge() is bytes."""
    xml1 = """<?xml version="1.0" ?><coverage><packages/></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    merger = CoberturaMerger([f1])
    merged_report = merger.merge()
    assert isinstance(merged_report, bytes)


def test_merge_xml_declaration(make_file):
    """Test that the merged report has an XML declaration."""
    xml1 = """<?xml version="1.0" ?><coverage><packages/></coverage>"""
    f1 = make_file("coverage1.xml", xml1)
    merger = CoberturaMerger([f1])
    merged_report = merger.merge()
    assert merged_report.startswith(b'<?xml version=\'1.0\' encoding=\'utf-8\'?>')
