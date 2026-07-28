"""
File Processor
Handles PDF conversion, image preprocessing, and format conversion
"""

import fitz  # PyMuPDF
import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple
import tempfile
from PIL import Image


class FileProcessor:
    """Process various file formats for detection"""
    
    def __init__(
        self,
        noise_threshold: float = 3.0,
        max_denoise_megapixels: float = 12.0
    ):
        """
        Initialize file processor

        Args:
            noise_threshold: Estimated noise, in grey levels, above which an
                image is worth denoising. A page rendered from a vector PDF
                measures ~0; a scan measures well into double figures.
            max_denoise_megapixels: Above this size, denoise with a bounded
                filter instead of the non-local-means one, whose cost grows
                with the pixel count and reaches minutes on a plotted sheet.
        """
        self.supported_image_formats = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}
        self.supported_doc_formats = {'.pdf'}
        # DWG support requires external tools (ezdxf, etc.)
        self.supported_cad_formats = {'.dwg', '.dxf'}
        self.noise_threshold = noise_threshold
        self.max_denoise_megapixels = max_denoise_megapixels
    
    
    async def process_file(self, file_path: Path, dpi: int = 400) -> List[Path]:
        """
        Process file and return list of image paths
        
        Args:
            file_path: Input file path
            dpi: Resolution for PDF conversion
            
        Returns:
            List of processed image paths
        """
        
        file_ext = file_path.suffix.lower()
        
        if file_ext in self.supported_image_formats:
            # Already an image - preprocess and return
            processed = await self._preprocess_image(file_path)
            return [processed]
        
        elif file_ext in self.supported_doc_formats:
            # PDF - convert to images
            return await self._pdf_to_images(file_path, dpi)
        
        elif file_ext in self.supported_cad_formats:
            # CAD file - convert to image
            return await self._cad_to_images(file_path, dpi)
        
        else:
            raise ValueError(f"Unsupported file format: {file_ext}")
    
    
    async def _pdf_to_images(self, pdf_path: Path, dpi: int) -> List[Path]:
        """
        Convert PDF to images
        
        Args:
            pdf_path: Path to PDF file
            dpi: Resolution
            
        Returns:
            List of image paths
        """
        
        print(f"📄 Converting PDF: {pdf_path.name} at {dpi} DPI")
        
        output_dir = pdf_path.parent / "converted"
        output_dir.mkdir(exist_ok=True)
        
        image_paths = []
        
        # Open PDF
        pdf_document = fitz.open(pdf_path)
        
        # Convert each page
        for page_num in range(len(pdf_document)):
            page = pdf_document[page_num]
            
            # Calculate zoom factor for DPI
            zoom = dpi / 72  # PDF default is 72 DPI
            matrix = fitz.Matrix(zoom, zoom)
            
            # Render page to pixmap
            pix = page.get_pixmap(matrix=matrix)
            
            # Save as PNG
            output_path = output_dir / f"{pdf_path.stem}_page_{page_num + 1}.png"
            pix.save(str(output_path))
            
            # Preprocess image
            processed_path = await self._preprocess_image(output_path)
            image_paths.append(processed_path)
        
        pdf_document.close()
        
        print(f"✅ Converted {len(image_paths)} pages")
        
        return image_paths
    
    
    async def _preprocess_image(self, image_path: Path) -> Path:
        """
        Preprocess image for better detection
        
        Args:
            image_path: Path to image
            
        Returns:
            Path to preprocessed image
        """
        
        # Read image
        img = cv2.imread(str(image_path))
        
        if img is None:
            raise ValueError(f"Could not read image: {image_path}")
        
        # Create preprocessed directory
        preprocessed_dir = image_path.parent / "preprocessed"
        preprocessed_dir.mkdir(exist_ok=True)
        
        output_path = preprocessed_dir / f"preprocessed_{image_path.name}"
        
        # Apply preprocessing
        processed = self._adaptive_preprocess(img)
        
        # Save preprocessed image
        cv2.imwrite(str(output_path), processed)
        
        return output_path
    
    
    def _adaptive_preprocess(self, img: np.ndarray) -> np.ndarray:
        """
        Adaptive preprocessing based on image characteristics
        
        Args:
            img: Input image
            
        Returns:
            Preprocessed image
        """
        
        # Convert to grayscale for analysis
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        
        # Calculate image statistics
        mean_intensity = np.mean(gray)
        std_intensity = np.std(gray)
        
        # Decide preprocessing strategy
        if mean_intensity < 100:  # Dark image
            # Increase brightness and contrast
            img = self._adjust_brightness_contrast(img, alpha=1.2, beta=30)
        
        elif std_intensity < 30:  # Low contrast
            # Enhance contrast
            img = self._enhance_contrast(img)

        # Apply noise reduction, but only where there is noise to remove.
        # Denoising a page rendered from a vector PDF costs minutes and removes
        # nothing, because there is nothing there to remove.
        noise = self._estimate_noise(gray)
        if noise >= self.noise_threshold:
            img = self._denoise(img, noise)

        # Sharpen
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        img = cv2.filter2D(img, -1, kernel)

        return img


    def _estimate_noise(self, gray: np.ndarray, sample: int = 1024) -> float:
        """
        Estimate the image's noise in grey levels.

        Uses the median absolute Laplacian, which ignores the edges that line
        work is made of and responds to the speckle a scan carries. Measured on
        a central sample so the cost does not grow with the sheet size.

        Args:
            gray: Grayscale image
            sample: Side of the square sampled from the middle of the image

        Returns:
            Estimated noise standard deviation
        """

        height, width = gray.shape[:2]
        y = max(0, (height - sample) // 2)
        x = max(0, (width - sample) // 2)
        patch = gray[y:y + sample, x:x + sample]

        if patch.size == 0:
            return 0.0

        laplacian = cv2.Laplacian(patch, cv2.CV_64F)

        # 1.4826 scales a median absolute deviation to a standard deviation.
        return float(np.median(np.abs(laplacian)) * 1.4826)


    def _denoise(self, img: np.ndarray, noise: float) -> np.ndarray:
        """
        Remove speckle, at a cost that stays bounded on large sheets.

        Args:
            img: Input image
            noise: Estimated noise, from _estimate_noise

        Returns:
            Denoised image
        """

        megapixels = (img.shape[0] * img.shape[1]) / 1e6

        if megapixels > self.max_denoise_megapixels:
            print(f"🧹 Denoising {megapixels:.0f} MP image (noise ~{noise:.1f}) "
                  f"with a median filter to keep processing bounded")
            return cv2.medianBlur(img, 3)

        print(f"🧹 Denoising {megapixels:.1f} MP image (noise ~{noise:.1f})")

        return cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)
    
    
    def _adjust_brightness_contrast(
        self,
        img: np.ndarray,
        alpha: float = 1.0,
        beta: int = 0
    ) -> np.ndarray:
        """
        Adjust brightness and contrast
        
        Args:
            img: Input image
            alpha: Contrast control (1.0-3.0)
            beta: Brightness control (0-100)
            
        Returns:
            Adjusted image
        """
        return cv2.convertScaleAbs(img, alpha=alpha, beta=beta)
    
    
    def _enhance_contrast(self, img: np.ndarray) -> np.ndarray:
        """
        Enhance contrast using CLAHE
        
        Args:
            img: Input image
            
        Returns:
            Contrast-enhanced image
        """
        
        # Convert to LAB color space
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        # Apply CLAHE to L channel
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        l = clahe.apply(l)
        
        # Merge channels
        lab = cv2.merge([l, a, b])
        
        # Convert back to BGR
        img = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        
        return img
    
    
    # Long side of a rendered DXF sheet, in inches. A DXF has no paper size,
    # so this stands in for one: 24" at the job DPI puts symbols at the same
    # pixel scale as a PDF plotted on ARCH D and rendered the same way.
    CAD_SHEET_INCHES = 24.0

    async def _cad_to_images(self, cad_path: Path, dpi: int) -> List[Path]:
        """
        Convert a DXF file to an image.

        The modelspace is drawn with ezdxf's rendering add-on as black line
        work on white, which is what the detector was trained on. DWG stays
        unsupported: it is a closed format, and reading it takes the ODA
        converter, not a Python library.

        Args:
            cad_path: Path to CAD file
            dpi: Resolution

        Returns:
            List of image paths (one - a DXF has a single modelspace)
        """

        if cad_path.suffix.lower() == '.dwg':
            raise ValueError(
                "DWG files cannot be read directly. Export the drawing to DXF "
                "or plot it to PDF, then upload that."
            )

        from ezdxf import recover
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.config import (
            BackgroundPolicy, ColorPolicy, Configuration,
        )
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import pyplot as plt

        print(f"📐 Converting DXF: {cad_path.name} at {dpi} DPI")

        # recover reads files with the structural damage real-world exports
        # carry, which plain readfile refuses.
        doc, _auditor = recover.readfile(str(cad_path))
        msp = doc.modelspace()
        if len(msp) == 0:
            raise ValueError(f"DXF has an empty modelspace: {cad_path.name}")

        output_dir = cad_path.parent / "converted"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{cad_path.stem}.png"

        fig = plt.figure()
        ax = fig.add_axes([0, 0, 1, 1])
        config = Configuration(
            background_policy=BackgroundPolicy.WHITE,
            color_policy=ColorPolicy.BLACK,
        )
        try:
            Frontend(RenderContext(doc), MatplotlibBackend(ax),
                     config=config).draw_layout(msp, finalize=True)

            # Size the sheet after drawing, when the axes hold the extents.
            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()
            aspect = (y1 - y0) / max(x1 - x0, 1e-9)
            if aspect <= 1.0:
                fig.set_size_inches(
                    self.CAD_SHEET_INCHES,
                    max(self.CAD_SHEET_INCHES * aspect, 0.1),
                )
            else:
                fig.set_size_inches(
                    max(self.CAD_SHEET_INCHES / aspect, 0.1),
                    self.CAD_SHEET_INCHES,
                )

            fig.savefig(output_path, dpi=dpi)
        finally:
            plt.close(fig)

        processed = await self._preprocess_image(output_path)
        return [processed]
    
    
    def get_image_info(self, image_path: Path) -> dict:
        """
        Get image metadata
        
        Args:
            image_path: Path to image
            
        Returns:
            Image information dictionary
        """
        
        img = cv2.imread(str(image_path))
        
        if img is None:
            return {"error": "Could not read image"}
        
        height, width = img.shape[:2]
        channels = img.shape[2] if len(img.shape) == 3 else 1
        
        return {
            "filename": image_path.name,
            "width": width,
            "height": height,
            "channels": channels,
            "size_bytes": image_path.stat().st_size,
            "format": image_path.suffix.upper()[1:]
        }
    
    
    def resize_image(
        self,
        image_path: Path,
        max_size: int = 1920
    ) -> Path:
        """
        Resize image if too large
        
        Args:
            image_path: Path to image
            max_size: Maximum width or height
            
        Returns:
            Path to resized image
        """
        
        img = cv2.imread(str(image_path))
        height, width = img.shape[:2]
        
        if max(width, height) <= max_size:
            return image_path
        
        # Calculate new dimensions
        if width > height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))
        
        # Resize
        resized = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_AREA)
        
        # Save
        output_path = image_path.parent / f"resized_{image_path.name}"
        cv2.imwrite(str(output_path), resized)
        
        return output_path
