param(
    [Parameter(Mandatory = $true)][string]$PrinterName,
    [Parameter(Mandatory = $true)][string]$PageListPath,
    [Parameter(Mandatory = $true)][double]$WidthMm,
    [Parameter(Mandatory = $true)][double]$HeightMm
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$script:pagePaths = @(Get-Content -LiteralPath $PageListPath -Encoding UTF8)
$script:pageIndex = 0
if ($script:pagePaths.Count -eq 0) { throw 'No label pages to print' }

$document = New-Object System.Drawing.Printing.PrintDocument
try {
    $document.PrinterSettings.PrinterName = $PrinterName
    if (-not $document.PrinterSettings.IsValid) { throw 'Printer is unavailable' }
    $document.PrintController = New-Object System.Drawing.Printing.StandardPrintController
    $document.DocumentName = '标签打印'
    $document.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins(0, 0, 0, 0)
    $width = [Math]::Max(1, [int][Math]::Round($WidthMm * 100 / 25.4))
    $height = [Math]::Max(1, [int][Math]::Round($HeightMm * 100 / 25.4))
    $document.DefaultPageSettings.PaperSize = New-Object System.Drawing.Printing.PaperSize('标签', $width, $height)
    $document.add_PrintPage({
        param($sender, $event)
        $image = [System.Drawing.Image]::FromFile($script:pagePaths[$script:pageIndex])
        try {
            $event.Graphics.DrawImage($image, $event.PageBounds)
        } finally {
            $image.Dispose()
        }
        $script:pageIndex++
        $event.HasMorePages = $script:pageIndex -lt $script:pagePaths.Count
    })
    $document.Print()
} finally {
    $document.Dispose()
}
