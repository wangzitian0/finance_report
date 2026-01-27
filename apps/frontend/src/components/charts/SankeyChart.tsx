"use client";

import dynamic from "next/dynamic";
import { useMemo, useState, useEffect, useCallback } from "react";

const ReactECharts = dynamic(
  () => import("echarts-for-react").catch(() => {
    // Return a fallback component if chunk fails to load
    return { default: () => <div className="text-sm text-muted text-center p-4">Failed to load chart. Please refresh.</div> };
  }),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center text-muted" style={{ height: "400px" }}>
        <div className="text-center">
          <div className="inline-block w-6 h-6 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
          <p className="text-sm">Loading chart...</p>
        </div>
      </div>
    ),
  }
);

/**
 * Resolve CSS variable to computed color value.
 * ECharts uses Canvas rendering and cannot interpret CSS variable strings.
 */
function getCSSVar(varName: string): string {
  if (typeof window === "undefined") return "#888";
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || "#888";
}

interface SankeyItem {
  category: string;
  subcategory: string;
  amount: number | string;
}

interface SankeyChartProps {
  operating?: SankeyItem[];
  investing?: SankeyItem[];
  financing?: SankeyItem[];
  title?: string;
  height?: number;
}

const toNumber = (value: number | string): number => {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (value === null || value === undefined) return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export function SankeyChart({
  operating = [],
  investing = [],
  financing = [],
  title = "Cash Flow",
  height = 400,
}: SankeyChartProps) {
  const [colorKey, setColorKey] = useState(0);

  const handleThemeChange = useCallback(() => {
    setColorKey((k) => k + 1);
  }, []);

  useEffect(() => {
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.attributeName === "class" || mutation.attributeName === "data-theme") {
          handleThemeChange();
          break;
        }
      }
    });
    observer.observe(document.documentElement, { attributes: true });
    return () => observer.disconnect();
  }, [handleThemeChange]);

  const option = useMemo(() => {
    const successColor = getCSSVar("--success");
    const errorColor = getCSSVar("--error");
    const accentColor = getCSSVar("--accent");
    const warningColor = getCSSVar("--warning");
    const foregroundColor = getCSSVar("--foreground");
    const foregroundMutedColor = getCSSVar("--foreground-muted");

    const nodes: { name: string; itemStyle?: { color: string } }[] = [];
    const links: { source: string; target: string; value: number }[] = [];

    const addCategory = (items: SankeyItem[], color: string, prefix: string) => {
      const inflowItems = items.filter((i) => toNumber(i.amount) > 0);
      const outflowItems = items.filter((i) => toNumber(i.amount) < 0);
      
      if (inflowItems.length === 0 && outflowItems.length === 0) return;

      nodes.push({ name: prefix, itemStyle: { color } });
      nodes.push({ name: `${prefix}-Inflows`, itemStyle: { color: successColor } });
      nodes.push({ name: `${prefix}-Outflows`, itemStyle: { color: errorColor } });

      inflowItems.forEach((item) => {
        const amount = toNumber(item.amount);
        nodes.push({ name: `${prefix}-${item.subcategory}`, itemStyle: { color: foregroundMutedColor } });
        links.push({
          source: `${prefix}-Inflows`,
          target: `${prefix}-${item.subcategory}`,
          value: amount,
        });
      });

      outflowItems.forEach((item) => {
        const rawValue = toNumber(item.amount);
        const amount = Math.abs(rawValue);
        nodes.push({ name: `${prefix}-${item.subcategory}`, itemStyle: { color: foregroundMutedColor } });
        links.push({
          source: `${prefix}-${item.subcategory}`,
          target: `${prefix}-Outflows`,
          value: amount,
        });
      });
    };

    addCategory(operating, successColor, "Operating");
    addCategory(investing, accentColor, "Investing");
    addCategory(financing, warningColor, "Financing");

    const hasData = nodes.length > 0;

    if (!hasData) {
      return {
        title: { text: title, left: "center", textStyle: { color: foregroundMutedColor } },
        graphic: {
          type: "text",
          left: "center",
          top: "middle",
          style: {
            text: "Add transaction data to see cash flow visualization",
            fill: foregroundMutedColor,
            fontSize: 14,
          },
        },
      };
    }

    return {
      title: { text: title, left: "center", textStyle: { color: foregroundColor } },
      tooltip: {
        trigger: "item",
        triggerOn: "mousemove",
        formatter: (params: { data: { name?: string; value?: number; source?: string; target?: string } }) => {
          if (params.data.source && params.data.target) {
            return `${params.data.source} → ${params.data.target}: ${params.data.value?.toLocaleString()}`;
          }
          return `${params.data.name}: ${params.data.value?.toLocaleString()}`;
        },
      },
      series: [
        {
          type: "sankey",
          layout: "none",
          emphasis: { focus: "adjacency" },
          data: nodes,
          links: links,
          left: "5%",
          right: "5%",
          top: "10%",
          bottom: "10%",
          nodeWidth: 20,
          nodeGap: 12,
          lineStyle: {
            color: "gradient",
            curveness: 0.5,
          },
          label: {
            color: foregroundColor,
            fontSize: 11,
          },
        },
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- colorKey triggers re-computation on theme change
  }, [operating, investing, financing, title, colorKey]);

  return <ReactECharts option={option} style={{ height: `${height}px`, width: "100%" }} />;
}
