import { getNodesBounds, getViewportForBounds, type Node } from "@xyflow/react";
import { toPng, toSvg } from "html-to-image";

const MAX_IMAGE_SIZE = 4096;
const IMAGE_PADDING = 160;

export function readCssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function keepInExport(node: HTMLElement): boolean {
  if (!(node instanceof HTMLElement)) return true;
  return !(
    node.classList.contains("react-flow__minimap") ||
    node.classList.contains("react-flow__controls") ||
    node.hasAttribute("data-map-export-exclude")
  );
}

/** React Flow's documented "download image" approach: frame every node,
 * then render the viewport element at that transform with html-to-image.
 * Colours come from the live theme at export time, never a cached value. */
export async function downloadDiagramImage(
  nodes: Node[],
  format: "png" | "svg",
  fileBase: string,
): Promise<void> {
  const viewportEl = document.querySelector<HTMLElement>(".cp-map .react-flow__viewport");
  if (!viewportEl || nodes.length === 0) throw new Error("Nothing to export");
  const bounds = getNodesBounds(nodes);
  const width = Math.min(MAX_IMAGE_SIZE, Math.ceil(bounds.width + IMAGE_PADDING));
  const height = Math.min(MAX_IMAGE_SIZE, Math.ceil(bounds.height + IMAGE_PADDING));
  const viewport = getViewportForBounds(bounds, width, height, 0.1, 2, 0.08);
  const options = {
    backgroundColor: readCssVar("--cp-bg") || undefined,
    width,
    height,
    filter: keepInExport,
    style: {
      width: `${width}px`,
      height: `${height}px`,
      transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
    },
  };
  const dataUrl =
    format === "png" ? await toPng(viewportEl, options) : await toSvg(viewportEl, options);
  const link = document.createElement("a");
  link.download = `${fileBase}.${format}`;
  link.href = dataUrl;
  link.click();
}
