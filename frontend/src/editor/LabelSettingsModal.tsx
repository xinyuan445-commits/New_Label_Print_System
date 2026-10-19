import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Modal } from "../components/ui/Modal";

type Props = {
  open: boolean;
  onClose: () => void;
  widthMm: number;
  heightMm: number;
  cornerRadiusMm: number;
  onApply: (widthMm: number, heightMm: number, cornerRadiusMm: number) => void;
};

/** Common label sizes (mm) offered as one-click presets. */
const PRESETS: Array<{ w: number; h: number }> = [
  { w: 40, h: 100 },
  { w: 50, h: 30 },
  { w: 100, h: 180 },
  { w: 100, h: 150 },
  { w: 105, h: 148 },
  { w: 210, h: 297 },
];

export function LabelSettingsModal({
  open,
  onClose,
  widthMm,
  heightMm,
  cornerRadiusMm,
  onApply,
}: Props) {
  const { t } = useTranslation();
  const [w, setW] = useState(String(widthMm));
  const [h, setH] = useState(String(heightMm));
  const [radius, setRadius] = useState(String(cornerRadiusMm));

  // Re-seed the inputs whenever the modal opens on the current label size.
  useEffect(() => {
    if (open) {
      setW(String(widthMm));
      setH(String(heightMm));
      setRadius(String(cornerRadiusMm));
    }
  }, [open, widthMm, heightMm, cornerRadiusMm]);

  const wNum = Number(w);
  const hNum = Number(h);
  const radiusNum = Number(radius);
  const valid =
    Number.isFinite(wNum) &&
    Number.isFinite(hNum) &&
    wNum > 0 &&
    wNum <= 1000 &&
    hNum > 0 &&
    hNum <= 1000 &&
    Number.isFinite(radiusNum) &&
    radiusNum >= 0 &&
    radiusNum <= Math.min(wNum, hNum) / 2;

  const apply = () => {
    if (!valid) return;
    onApply(wNum, hNum, radiusNum);
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("labelSize.title")}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button onClick={apply} disabled={!valid}>
            {t("labelSize.apply")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-400">{t("labelSize.help")}</p>
        <div className="flex items-end gap-3">
          <Input
            label={t("labelSize.width")}
            type="number"
            min={1}
            max={1000}
            step="0.1"
            value={w}
            onChange={(e) => setW(e.target.value)}
          />
          <span className="pb-2 text-slate-500">×</span>
          <Input
            label={t("labelSize.height")}
            type="number"
            min={1}
            max={1000}
            step="0.1"
            value={h}
            onChange={(e) => setH(e.target.value)}
          />
          <span className="pb-2 text-sm text-slate-500">mm</span>
        </div>
        <div className="flex gap-2">
          <Button
            variant={wNum > hNum ? "primary" : "secondary"}
            disabled={!wNum || !hNum}
            onClick={() => {
              if (wNum < hNum) {
                setW(h);
                setH(w);
              }
            }}
          >
            {t("templates.landscape")}
          </Button>
          <Button
            variant={hNum > wNum ? "primary" : "secondary"}
            disabled={!wNum || !hNum}
            onClick={() => {
              if (wNum > hNum) {
                setW(h);
                setH(w);
              }
            }}
          >
            {t("templates.portrait")}
          </Button>
        </div>
        <Input
          label={t("labelSize.cornerRadius")}
          type="number"
          min={0}
          max={Number.isFinite(wNum) && Number.isFinite(hNum) ? Math.min(wNum, hNum) / 2 : 0}
          step="0.1"
          value={radius}
          onChange={(e) => setRadius(e.target.value)}
        />
        <div>
          <p className="mb-1 text-xs text-slate-500">{t("labelSize.presets")}</p>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={`${p.w}x${p.h}`}
                type="button"
                onClick={() => {
                  setW(String(p.w));
                  setH(String(p.h));
                }}
                className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
              >
                {p.w}×{p.h}
              </button>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  );
}
