"use client";

import ReactECharts from "echarts-for-react";
import { useMemo } from "react";

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
  const option = useMemo(() => {
    const nodes: { name: string; itemStyle?: { color: string } }[] = [];
    const links: { source: string; target: string; value: number }[] = [];

    const addCategory = (items: SankeyItem[], color: string, prefix: string) => {
      const inflowItems = items.filter((i) => toNumber(i.amount) > 0);
      const outflowItems = items.filter((i) => toNumber(i.amount) < 0);
      
      if (inflowItems.length === 0 && outflowItems.length === 0) return;

      nodes.push({ name: prefix, itemStyle: { color } });
      nodes.push({ name: `${prefix}-Inflows`, itemStyle: { color: "#22c55e" } });
      nodes.push({ name: `${prefix}-Outflows`, itemStyle: { color: "#ef4444" } });

      inflowItems.forEach((item) => {
        const amount = toNumber(item.amount);
        nodes.push({ name: `${prefix}-${item.subcategory}`, itemStyle: { color: "#64748b" } });
        links.push({
          source: `${prefix}-Inflows`,
          target: `${prefix}-${item.subcategory}`,
          value: amount,
        });
      });

      outflowItems.forEach((item) => {
        const rawValue = toNumber(item.amount);
        const amount = Math.abs(rawValue);
        nodes.push({ name: `${prefix}-${item.subcategory}`, itemStyle: { color: "#64748b" } });
        links.push({
          source: `${prefix}-${item.subcategory}`,
          target: `${prefix}-Outflows`,
          value: amount,
        });
      });
    };

    addCategory(operating, "#22c55e", "Operating");
    addCategory(investing, "#8b5cf6", "Investing");
    addCategory(financing, "#f59e0b", "Financing");

    const hasData = nodes.length > 0;

    if (!hasData) {
      return {
        title: { text: title, left: "center", textStyle: { color: "#64748b" } },
        graphic: {
          type: "text",
          left: "center",
          top: "middle",
          style: {
            text: "Add transaction data to see cash flow visualization",
            fill: "#94a3b8",
            fontSize: 14,
          },
        },
      };
    }

    return {
      title: { text: title, left: "center" },
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
            color: "#1e293b",
            fontSize: 11,
          },
        },
      ],
    };
  }, [operating, investing, financing, title]);

  return <ReactECharts option={option} style={{ height: `${height}px`, width: "100%" }} />;
}
