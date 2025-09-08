import lxml.etree as ET
import re
from datetime import datetime


def _parse_condition_coverage(cc_string):
    """Parse condition coverage string like '50% (1/2)'."""
    if not cc_string:
        return 0, 0
    match = re.search(r"\((\d+)/(\d+)\)", cc_string)
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _get_coverage_percentage(cc_string):
    """Get percentage from condition coverage string."""
    if not cc_string:
        return -1.0
    try:
        return float(cc_string.split("%", 1)[0])
    except (ValueError, IndexError):
        return -1.0


class CoberturaMerger:
    """
    A class to merge multiple Cobertura reports.
    The merge strategy is:
    - Line hits are summed.
    - Branch coverage is merged optimistically (takes the highest coverage).
    - All rates are recalculated after merging.
    """

    def __init__(self, filenames):
        if not filenames:
            raise ValueError("At least one Cobertura file is required.")
        self.filenames = filenames
        self.base_tree = ET.parse(self.filenames[0]).getroot()

        self._class_map = {
            el.get("filename"): el for el in self.base_tree.xpath("./packages//class")
        }
        self._package_map = {
            el.get("name"): el for el in self.base_tree.xpath("./packages/package")
        }

    def merge(self):
        """
        Merge the coverage files and return the merged report as a string.
        """
        for filename in self.filenames[1:]:
            new_tree = ET.parse(filename).getroot()
            self._merge_sources(new_tree)
            for new_class in new_tree.xpath("./packages//class"):
                self._merge_class(new_class)

        self._recalculate_all_rates()
        self._update_timestamp()

        return ET.tostring(
            self.base_tree, pretty_print=True, encoding="utf-8", xml_declaration=True
        )

    def _merge_sources(self, new_tree):
        base_sources = self.base_tree.find("sources")
        if base_sources is None:
            base_sources = ET.Element("sources")
            self.base_tree.insert(0, base_sources)

        existing_sources = {s.text for s in base_sources.findall("source")}

        new_sources_el = new_tree.find("sources")
        if new_sources_el is not None:
            for source in new_sources_el.findall("source"):
                if source.text not in existing_sources:
                    base_sources.append(source)
                    existing_sources.add(source.text)

    def _merge_class(self, new_class):
        class_filename = new_class.get("filename")
        base_class = self._class_map.get(class_filename)

        if base_class is None:
            # Class does not exist in base, add it.
            package_name = new_class.xpath("ancestor::package[1]")[0].get("name")
            base_package = self._package_map.get(package_name)
            if base_package is None:
                packages_el = self.base_tree.find("packages")
                if packages_el is None:
                    packages_el = ET.SubElement(self.base_tree, "packages")
                base_package = ET.SubElement(packages_el, "package", name=package_name)
                ET.SubElement(base_package, "classes")
                self._package_map[package_name] = base_package

            base_package.find("classes").append(new_class)
            self._class_map[class_filename] = new_class
            return

        # Class exists, merge lines.
        base_lines_map = {l.get("number"): l for l in base_class.xpath("lines/line")}
        for new_line in new_class.xpath("lines/line"):
            lineno = new_line.get("number")
            base_line = base_lines_map.get(lineno)

            if base_line is None:
                lines_el = base_class.find("lines")
                if lines_el is None:
                    lines_el = ET.SubElement(base_class, "lines")
                lines_el.append(new_line)
                base_lines_map[lineno] = new_line
            else:
                # Sum hits
                new_hits = int(new_line.get("hits", 0))
                base_hits = int(base_line.get("hits", 0))
                base_line.set("hits", str(base_hits + new_hits))

                # Merge branch coverage optimistically
                if new_line.get("branch") == "true":
                    base_line.set("branch", "true")

                    base_cc = base_line.get("condition-coverage")
                    new_cc = new_line.get("condition-coverage")

                    if _get_coverage_percentage(new_cc) > _get_coverage_percentage(
                        base_cc
                    ):
                        if new_cc:
                            base_line.set("condition-coverage", new_cc)

                        # Replace conditions element
                        base_conditions = base_line.find("conditions")
                        if base_conditions is not None:
                            base_line.remove(base_conditions)

                        new_conditions = new_line.find("conditions")
                        if new_conditions is not None:
                            base_line.append(new_conditions)

    def _recalculate_all_rates(self):
        total_lines, covered_lines, total_branches, covered_branches = (0, 0, 0, 0)
        for package_el in self.base_tree.xpath("packages/package"):
            tl, cl, tb, cb = self._recalculate_package_rates(package_el)
            total_lines += tl
            covered_lines += cl
            total_branches += tb
            covered_branches += cb

        line_rate = (covered_lines / total_lines) if total_lines > 0 else 0
        branch_rate = (covered_branches / total_branches) if total_branches > 0 else 0

        self.base_tree.set("line-rate", str(line_rate))
        self.base_tree.set("branch-rate", str(branch_rate))

    def _recalculate_package_rates(self, package_element):
        """Recalculate rates for a package and all its classes."""
        pkg_total_lines, pkg_covered_lines = 0, 0
        pkg_total_branches, pkg_covered_branches = 0, 0

        for class_el in package_element.xpath("classes/class"):
            tl, cl, tb, cb = self._recalculate_class_rates(class_el)
            pkg_total_lines += tl
            pkg_covered_lines += cl
            pkg_total_branches += tb
            pkg_covered_branches += cb

        line_rate = (pkg_covered_lines / pkg_total_lines) if pkg_total_lines > 0 else 0
        branch_rate = (
            (pkg_covered_branches / pkg_total_branches) if pkg_total_branches > 0 else 0
        )

        package_element.set("line-rate", str(line_rate))
        package_element.set("branch-rate", str(branch_rate))

        return pkg_total_lines, pkg_covered_lines, pkg_total_branches, pkg_covered_branches

    def _recalculate_class_rates(self, class_element):
        """Recalculate rates for a single class."""
        total_lines, covered_lines = 0, 0
        total_branches, covered_branches = 0, 0

        lines = class_element.xpath("lines/line")
        total_lines = len(lines)

        for line in lines:
            if int(line.get("hits", 0)) > 0:
                covered_lines += 1

            if line.get("branch") == "true":
                cc_string = line.get("condition-coverage")
                covered, total = _parse_condition_coverage(cc_string)
                total_branches += total
                covered_branches += covered

        line_rate = (covered_lines / total_lines) if total_lines > 0 else 0
        branch_rate = (covered_branches / total_branches) if total_branches > 0 else 0

        class_element.set("line-rate", str(line_rate))
        class_element.set("branch-rate", str(branch_rate))

        return total_lines, covered_lines, total_branches, covered_branches

    def _update_timestamp(self):
        self.base_tree.set("timestamp", str(int(datetime.now().timestamp())))
