# Labels and Printing

PantrLytics can generate and print inventory labels with item details and a scannable QR code. Printing requires a CUPS/IPP printer on your local network. Without a printer configured, you can still preview and download labels as PNG images.

---

## How labels work

Each item label contains:
- Item name and serial number
- Key dates (use-by, cook date if set)
- Category, location, and bin
- A QR code that links to the item's detail page

The QR code URL is built from the `base_url` you set in the add-on config. If `base_url` is wrong or missing, QR scans will fail. See [Getting Started](getting-started.md) for how to set it correctly.

---

## Printing a label from an item

1. Open the item detail page.
2. Choose how many copies you want and click **Choose label & print**.
3. Select the profile and review its preview. The current default small-label profile is preselected.
4. Check that the matching roll is loaded and no earlier jobs for the other roll are pending, then confirm and print.

The optional **Pantry — removable 62 × 30 mm** profile is for 62 mm continuous removable stock. It sets the wider layout, continuous-tape media and 30 mm cut length together on that print job. The existing small profile keeps its prior layout and media settings. The printer cannot detect the adhesive type; swapping rolls and confirming the selection are manual steps.

If no printer is configured, the button will not send to a printer — use **Preview Label** instead.

---

## Previewing a label

Click **Preview Label** on the item detail page to open the label as a PNG in a new browser tab. You can save or print it from there using your browser's print function.

---

## Label Designer

The **Designer** page (accessible from the sidebar or bottom nav) has two sections:

### Quick Label
For one-off labels that are not linked to any inventory item — useful for boxes, bins, or anything you want to label on the fly.

- Enter a **Title** (large text) and optional **Description** (smaller text).
- Click **Preview** to see the PNG. Quick labels use the existing small stock; confirm that roll is loaded before clicking **Print quick label**.

### Presets
Presets control how item labels look and which media settings accompany the print job. Choose the profile on the print confirmation page. You can set which profile is preselected from the preset cards.

- **Printer side**: For twin-roll printers, choose Auto, Left, or Right to select which roll is used.
- The default preset is highlighted on its card; creating the pantry profile does not change the existing default.

---

## Printer requirements

- A CUPS/IPP print server must be reachable on your local network.
- The add-on config needs `ipp_host` (e.g. `192.168.1.50:631`) and `ipp_printer` (the CUPS queue name).
- If the printer is unreachable or not configured, print actions fall back to PNG preview.

See [Printer Setup](printer-setup.md) for full setup instructions.

---

## Multiple copies

When printing from an item, set the copy count before clicking Print. All copies are submitted as a single CUPS job (one job with repeated pages), keeping your print queue tidy.

---

## QR code troubleshooting

If scanning a label opens the wrong page, times out, or shows a 401 error:

1. Check `base_url` in Admin → Configuration. It must be a URL reachable by the scanning device.
2. Use your HA host's LAN IP and the mapped port — not the HA ingress URL.
3. After fixing `base_url`, **reprint labels** for existing items. Old labels still carry the old URL.
