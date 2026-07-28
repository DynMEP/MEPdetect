"""
Result Exporter
Export detection results to various formats (JSON, CSV, Excel)
"""

import json
import csv
import re
import zipfile
import pandas as pd
from pathlib import Path
from typing import Dict, List
from datetime import datetime


class ResultExporter:
    """Export detection results to multiple formats"""
    
    def __init__(self):
        """Initialize result exporter"""
        self.supported_formats = {'json', 'csv', 'excel', 'xlsx', 'netlist',
                                  'dxf', 'pdf'}
    
    
    async def export(
        self,
        results: Dict,
        output_dir: Path,
        formats: List[str]
    ) -> Dict[str, str]:
        """
        Export results to specified formats
        
        Args:
            results: Detection results dictionary
            output_dir: Output directory
            formats: List of export formats
            
        Returns:
            Dictionary mapping format to file path
        """
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        exported_files = {}
        
        print(f"📦 Starting export for formats: {formats}")
        
        for fmt in formats:
            fmt = fmt.lower().strip()
            
            print(f"🔄 Processing format: {fmt}")
            
            if fmt not in self.supported_formats:
                print(f"⚠️  Unsupported format: {fmt}")
                continue
            
            try:
                if fmt == 'json':
                    file_path = await self._export_json(results, output_dir)
                    exported_files['json'] = str(file_path)
                
                elif fmt == 'csv':
                    file_path = await self._export_csv(results, output_dir)
                    exported_files['csv'] = str(file_path)
                
                elif fmt in {'excel', 'xlsx'}:
                    print(f"📊 Exporting Excel...")
                    file_path = await self._export_excel(results, output_dir)
                    exported_files['excel'] = str(file_path)
                    print(f"✅ Excel exported successfully")

                elif fmt == 'netlist':
                    if not results.get('circuits'):
                        print("ℹ️  No circuit data to export (tracing not requested)")
                        continue
                    file_path = self.generate_netlist(results, output_dir)
                    exported_files['netlist'] = str(file_path)

                elif fmt == 'dxf':
                    file_path = self._export_dxf(results, output_dir)
                    exported_files['dxf'] = str(file_path)

                elif fmt == 'pdf':
                    file_path = self._export_pdf(results, output_dir)
                    exported_files['pdf'] = str(file_path)
            
            except Exception as e:
                print(f"❌ Failed to export {fmt}: {str(e)}")
                import traceback
                traceback.print_exc()
                continue
        
        print(f"✅ Export complete. Files: {list(exported_files.keys())}")
        return exported_files
    
    
    async def _export_json(self, results: Dict, output_dir: Path) -> Path:
        """
        Export results as JSON
        
        Args:
            results: Detection results
            output_dir: Output directory
            
        Returns:
            Path to JSON file
        """
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"detections_{timestamp}.json"
        
        # Prepare JSON data
        export_data = {
            "metadata": {
                "export_date": datetime.now().isoformat(),
                "format_version": "1.0"
            },
            "summary": {
                "total_detections": results.get('total_detections', 0),
                "class_counts": results.get('class_counts', {}),
                "confidence_average": results.get('confidence_avg', 0),
                "processing_time": results.get('processing_time', 0)
            },
            "detections": results.get('detections', [])
        }

        # Traced connectivity, when circuit tracing was requested
        if results.get('circuits'):
            export_data['circuits'] = results['circuits']

        # Job-level enrichments, when their features ran
        for key in ('calibration', 'tokens', 'reconciliation',
                    'cross_sheet_circuits'):
            if results.get(key):
                export_data[key] = results[key]

        # Write JSON
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"✅ Exported JSON: {output_path.name}")
        
        return output_path
    
    
    async def _export_csv(self, results: Dict, output_dir: Path) -> Path:
        """
        Export results as CSV
        
        Args:
            results: Detection results
            output_dir: Output directory
            
        Returns:
            Path to CSV file
        """
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"detections_{timestamp}.csv"
        
        # Flatten detections for CSV
        rows = []
        
        detections = results.get('detections', [])
        if not detections:
            # Create summary row if no detections
            rows.append({
                'Summary': 'No detections found'
            })
        else:
            for idx, det in enumerate(detections, 1):
                row = {
                    'Detection_ID': idx,
                    'Class': det.get('class_name', 'Unknown'),
                    'Confidence': round(det.get('confidence', 0), 3),
                    'Center_X': round(det.get('bbox', {}).get('center_x', 0), 2),
                    'Center_Y': round(det.get('bbox', {}).get('center_y', 0), 2),
                    'Width': round(det.get('bbox', {}).get('width', 0), 2),
                    'Height': round(det.get('bbox', {}).get('height', 0), 2),
                    'X1': round(det.get('bbox', {}).get('x1', 0), 2),
                    'Y1': round(det.get('bbox', {}).get('y1', 0), 2),
                    'X2': round(det.get('bbox', {}).get('x2', 0), 2),
                    'Y2': round(det.get('bbox', {}).get('y2', 0), 2)
                }
                rows.append(row)
        
        # Write CSV
        if rows:
            with open(output_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
        
        print(f"✅ Exported CSV: {output_path.name}")
        
        return output_path
    
    
    async def _export_excel(self, results: Dict, output_dir: Path) -> Path:
        """
        Export results as Excel with multiple sheets
        
        Args:
            results: Detection results
            output_dir: Output directory
            
        Returns:
            Path to Excel file
        """
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"detections_{timestamp}.xlsx"
        
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Sheet 1: Summary
            summary_data = {
                'Metric': [
                    'Total Detections',
                    'Average Confidence',
                    'Processing Time (s)',
                    'Export Date'
                ],
                'Value': [
                    results.get('total_detections', 0),
                    round(results.get('confidence_avg', 0), 3),
                    round(results.get('processing_time', 0), 2),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ]
            }
            df_summary = pd.DataFrame(summary_data)
            df_summary.to_excel(writer, sheet_name='Summary', index=False)
            
            # Sheet 2: Class Counts
            class_counts = results.get('class_counts', {})
            if class_counts:
                counts_data = {
                    'Symbol': list(class_counts.keys()),
                    'Count': list(class_counts.values())
                }
                df_counts = pd.DataFrame(counts_data)
                df_counts = df_counts.sort_values('Count', ascending=False)
                df_counts.to_excel(writer, sheet_name='Symbol Counts', index=False)
            
            # Sheet 3: Detailed Detections
            detections = results.get('detections', [])
            if detections:
                detailed_rows = []
                for idx, det in enumerate(detections, 1):
                    row = {
                        'ID': idx,
                        'Symbol': det.get('class_name', 'Unknown'),
                        'Confidence': round(det.get('confidence', 0), 3),
                        'Center X': round(det.get('bbox', {}).get('center_x', 0), 2),
                        'Center Y': round(det.get('bbox', {}).get('center_y', 0), 2),
                        'Width': round(det.get('bbox', {}).get('width', 0), 2),
                        'Height': round(det.get('bbox', {}).get('height', 0), 2),
                        'X1': round(det.get('bbox', {}).get('x1', 0), 2),
                        'Y1': round(det.get('bbox', {}).get('y1', 0), 2),
                        'X2': round(det.get('bbox', {}).get('x2', 0), 2),
                        'Y2': round(det.get('bbox', {}).get('y2', 0), 2)
                    }
                    detailed_rows.append(row)
                
                df_detailed = pd.DataFrame(detailed_rows)
                df_detailed.to_excel(writer, sheet_name='All Detections', index=False)
        
        print(f"✅ Exported Excel: {output_path.name}")
        
        return output_path
    
    
    NETLIST_FIELDS = [
        'Sheet', 'Circuit', 'Tag', 'Net', 'Role', 'Component', 'Symbol',
        'Confidence', 'X', 'Y', 'Panel', 'Conductors', 'Nodes', 'Length_px',
        'Length_real', 'Units'
    ]


    def generate_netlist(self, results: Dict, output_dir: Path) -> Path:
        """
        Export the traced circuit netlist as CSV

        Consumes the per-sheet output of CircuitTracer: one row per component
        landing on a traced net, one per component carrying a circuit tag, plus
        one per homerun arrow and per unwired symbol. The Role column says
        which, so a reader can tell a traced connection from an annotated one.

        Args:
            results: Detection results carrying a 'circuits' key
            output_dir: Output directory

        Returns:
            Path to netlist file
        """

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"netlist_{timestamp}.csv"

        rows = []

        for sheet_result in results.get('circuits', []):
            sheet = sheet_result.get('sheet', '')
            nets_by_id = {net['net_id']: net for net in sheet_result.get('nets', [])}

            for circuit in sheet_result.get('circuits', []):
                panels = ', '.join(circuit.get('panel_refs', []))

                for net_id in circuit.get('net_ids', []):
                    net = nets_by_id.get(net_id, {})

                    for connection in net.get('connections', []):
                        rows.append({
                            'Sheet': sheet,
                            'Circuit': circuit['circuit_id'],
                            'Tag': circuit.get('circuit_tag') or '',
                            'Net': net_id,
                            'Role': 'device',
                            'Component': connection['ref'],
                            'Symbol': connection['class_name'],
                            'Confidence': connection['confidence'],
                            'X': connection['terminal'][0],
                            'Y': connection['terminal'][1],
                            'Panel': panels,
                            'Conductors': '',
                            'Nodes': net.get('junction_count', 0),
                            'Length_px': net.get('length_px', 0)
                        })

            for circuit in sheet_result.get('tag_circuits', []):
                for device in circuit['devices']:
                    rows.append({
                        'Sheet': sheet,
                        'Circuit': '',
                        'Tag': circuit['circuit_tag'],
                        'Net': '',
                        'Role': 'annotated',
                        'Component': device['ref'],
                        'Symbol': device['class_name'],
                        'Confidence': '',
                        'X': '',
                        'Y': '',
                        'Panel': circuit.get('panel') or '',
                        'Conductors': '',
                        'Nodes': '',
                        'Length_px': ''
                    })

            for homerun in sheet_result.get('homeruns', []):
                rows.append({
                    'Sheet': sheet,
                    'Circuit': '',
                    'Tag': homerun.get('circuit_tag') or '',
                    'Net': '',
                    'Role': 'homerun',
                    'Component': '',
                    'Symbol': 'homerun_arrow',
                    'Confidence': '',
                    'X': homerun['x'],
                    'Y': homerun['y'],
                    'Panel': homerun.get('panel_ref') or '',
                    'Conductors': homerun.get('conductor_count') or '',
                    'Nodes': '',
                    'Length_px': ''
                })

            for orphan in sheet_result.get('unconnected_symbols', []):
                rows.append({
                    'Sheet': sheet,
                    'Circuit': '',
                    'Tag': '',
                    'Net': '',
                    'Role': 'unconnected',
                    'Component': orphan['ref'],
                    'Symbol': orphan['class_name'],
                    'Confidence': '',
                    'X': '',
                    'Y': '',
                    'Panel': '',
                    'Conductors': '',
                    'Nodes': '',
                    'Length_px': ''
                })

        # A calibrated job states its net lengths in real units too; the
        # pixel column stays, because it is what the overlay shows.
        calibration = results.get('calibration') or {}
        units_per_px = calibration.get('units_per_pixel')
        units = calibration.get('units', '')
        for row in rows:
            length_px = row.get('Length_px')
            if units_per_px and isinstance(length_px, (int, float)) and length_px:
                row['Length_real'] = round(length_px * units_per_px, 1)
                row['Units'] = units
            else:
                row['Length_real'] = ''
                row['Units'] = ''

        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.NETLIST_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        print(f"✅ Exported netlist: {output_path.name} ({len(rows)} rows)")

        return output_path


    # DXF layer scheme for the takeoff overlay
    DXF_LAYERS = {
        'MEPD-SYMBOL': 2,    # detection boxes (yellow)
        'MEPD-LABEL': 8,     # class labels (grey)
        'MEPD-HOMERUN': 1,   # homerun arrows and their tags (red)
    }

    DXF_INSUNITS = {'feet': 2, 'inches': 1, 'meters': 6, 'millimeters': 4}


    def _export_dxf(self, results: Dict, output_dir: Path) -> Path:
        """
        Export the takeoff as DXF overlays, one per sheet.

        Each detection becomes a labelled rectangle and each traced homerun a
        marked point, on their own layers, so the takeoff drops onto the
        original drawing as an xref in AutoCAD or Revit. A calibrated job is
        written in its real units; an uncalibrated one stays in pixels.

        Returns:
            Path to the DXF, or to a zip when the job spans several sheets.
        """

        import ezdxf

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        calibration = results.get('calibration') or {}
        upp = calibration.get('units_per_pixel') or 1.0
        units = calibration.get('units') if calibration.get('units_per_pixel') else None

        heights = self._sheet_heights(results)

        detections_by_sheet: Dict[str, List[Dict]] = {}
        for det in results.get('detections', []):
            detections_by_sheet.setdefault(det.get('sheet', ''), []).append(det)
        circuits_by_sheet = {
            sheet.get('sheet', ''): sheet for sheet in results.get('circuits', [])
        }

        # Preserve first-seen order; an empty name still yields one file.
        sheet_names = list(dict.fromkeys(
            list(detections_by_sheet) + list(circuits_by_sheet)
        )) or ['']

        paths = []
        for name in sheet_names:
            doc = ezdxf.new('R2018')
            doc.header['$INSUNITS'] = self.DXF_INSUNITS.get(units, 0)
            for layer, color in self.DXF_LAYERS.items():
                doc.layers.add(layer, color=color)
            msp = doc.modelspace()

            # Image Y grows down, DXF Y grows up. Without a readable image
            # height the flip mirrors about zero, which keeps orientation
            # right at the cost of negative coordinates.
            height = heights.get(name, 0)

            def point(x: float, y: float):
                return (x * upp, (height - y) * upp)

            text_heights = []
            for det in detections_by_sheet.get(name, []):
                bbox = det.get('bbox', {})
                x1, y1 = bbox.get('x1', 0), bbox.get('y1', 0)
                x2, y2 = bbox.get('x2', 0), bbox.get('y2', 0)
                msp.add_lwpolyline(
                    [point(x1, y1), point(x2, y1), point(x2, y2), point(x1, y2)],
                    close=True,
                    dxfattribs={'layer': 'MEPD-SYMBOL'},
                )

                label = str(det.get('class_name', 'symbol'))
                ratings = det.get('ratings') or {}
                if ratings:
                    label += " " + " ".join(
                        f"{r['value']}{kind.upper() if kind != 'voltage' else 'V'}"
                        if kind != 'equipment' else r['value']
                        for kind, r in sorted(ratings.items())
                    )
                text_height = max(0.35 * abs(y2 - y1) * upp, 1e-6)
                text_heights.append(text_height)
                msp.add_text(
                    label,
                    dxfattribs={'layer': 'MEPD-LABEL', 'height': text_height},
                ).set_placement(point(x1, y1 - 4))

            marker = (sorted(text_heights)[len(text_heights) // 2]
                      if text_heights else 12 * upp)
            for homerun in circuits_by_sheet.get(name, {}).get('homeruns', []):
                center = point(homerun['x'], homerun['y'])
                msp.add_circle(center, marker * 0.6,
                               dxfattribs={'layer': 'MEPD-HOMERUN'})
                tag = homerun.get('circuit_tag') or 'HOMERUN'
                conductors = homerun.get('conductor_count')
                if conductors:
                    tag += f" ({conductors}c)"
                msp.add_text(
                    tag,
                    dxfattribs={'layer': 'MEPD-HOMERUN', 'height': marker},
                ).set_placement((center[0] + marker, center[1] + marker))

            stem = re.sub(r'[^A-Za-z0-9_-]+', '_', Path(name).stem) or 'sheet'
            dxf_path = output_dir / f"takeoff_{stem}_{timestamp}.dxf"
            doc.saveas(dxf_path)
            paths.append(dxf_path)

        if len(paths) == 1:
            print(f"✅ Exported DXF: {paths[0].name}")
            return paths[0]

        zip_path = output_dir / f"takeoff_dxf_{timestamp}.zip"
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for path in paths:
                zipf.write(path, path.name)
        print(f"✅ Exported DXF: {zip_path.name} ({len(paths)} sheets)")
        return zip_path


    def _sheet_heights(self, results: Dict) -> Dict[str, int]:
        """Pixel height per sheet image, for flipping into DXF's Y-up."""

        heights: Dict[str, int] = {}
        for sheet in results.get('sheets', []):
            path = sheet.get('image_path')
            name = sheet.get('name')
            if not path or not name:
                continue
            try:
                from PIL import Image
                with Image.open(path) as image:
                    heights[name] = image.height
            except Exception:
                continue
        return heights


    def _export_pdf(self, results: Dict, output_dir: Path) -> Path:
        """
        Export a one-file summary report as PDF.

        The tabular deliverable an estimator forwards: totals, symbol counts,
        circuit summary, and the reconciliation findings when tracing ran.
        """

        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (
            Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"report_{timestamp}.pdf"

        styles = getSampleStyleSheet()
        body = styles['BodyText']

        def table(data, widths=None):
            grid = Table(data, colWidths=widths, hAlign='LEFT')
            grid.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2b3a55')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            return grid

        story = [
            Paragraph("MEPdetect Detection Report", styles['Title']),
            Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"), body),
            Spacer(1, 12),
        ]

        calibration = results.get('calibration') or {}
        scale_note = (
            f"{calibration['units_per_pixel']:.6f} {calibration['units']}/pixel"
            if calibration.get('units_per_pixel') else "not calibrated"
        )
        story.append(table([
            ['Metric', 'Value'],
            ['Total detections', results.get('total_detections', 0)],
            ['Average confidence', round(results.get('confidence_avg', 0), 3)],
            ['Sheets processed', results.get('num_images', 1)],
            ['Processing time (s)', round(results.get('processing_time', 0), 2)],
            ['Scale', scale_note],
        ], widths=[150, 250]))
        story.append(Spacer(1, 12))

        class_counts = results.get('class_counts', {})
        if class_counts:
            story.append(Paragraph("Symbol counts", styles['Heading2']))
            rows = [['Symbol', 'Count']] + [
                [name, count]
                for name, count in sorted(class_counts.items(),
                                          key=lambda item: -item[1])
            ]
            story.append(table(rows, widths=[250, 80]))
            story.append(Spacer(1, 12))

        circuit_summary = results.get('circuit_summary')
        if circuit_summary:
            story.append(Paragraph("Circuit tracing", styles['Heading2']))
            rows = [['Metric', 'Value']] + [
                [key.replace('_', ' '), value]
                for key, value in circuit_summary.items()
            ]
            story.append(table(rows, widths=[200, 120]))
            story.append(Spacer(1, 12))

        tokens = results.get('tokens') or {}
        if any(tokens.values()):
            story.append(Paragraph("Ratings and equipment read off the sheets",
                                   styles['Heading2']))
            rows = [['Kind', 'Values']] + [
                [kind, Paragraph(", ".join(values), body)]
                for kind, values in tokens.items() if values
            ]
            story.append(table(rows, widths=[90, 340]))
            story.append(Spacer(1, 12))

        reconciliation = results.get('reconciliation') or {}
        if reconciliation.get('findings'):
            story.append(Paragraph("Reconciliation", styles['Heading2']))
            rows = [['Severity', 'Item', 'Expected', 'Found', 'Note']] + [
                [finding['severity'], finding['item'],
                 '' if finding['expected'] is None else str(finding['expected']),
                 '' if finding['found'] is None else str(finding['found']),
                 Paragraph(finding['note'], body)]
                for finding in reconciliation['findings']
            ]
            story.append(table(rows, widths=[55, 110, 60, 60, 180]))

        SimpleDocTemplate(str(output_path), pagesize=letter).build(story)

        print(f"✅ Exported PDF report: {output_path.name}")

        return output_path
