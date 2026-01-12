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

const toNumber = (value: number | string) => typeof value === "string" ? Number(value) : value;

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
      const filtered = items.filter((i) => toNumber(i.amount) > 0);
      if (filtered.length === 0) return;

      const total = filtered.reduce((sum, i) => sum + toNumber(i.amount), 0);
      nodes.push({ name: prefix, itemStyle: { color } });

      filtered.forEach((item) => {
        const amount = toNumber(item.amount);
        nodes.push({ name: `${prefix}-${item.subcategory}`, itemStyle: { color: "#64748b" } });
        links.push({
          source: prefix,
          target: `${prefix}-${item.subcategory}`,
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
