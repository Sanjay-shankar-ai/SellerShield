import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches

def generate_architecture_diagram(output_png, output_svg=None):
    fig, ax = plt.subplots(figsize=(18, 12), dpi=200)
    fig.patch.set_facecolor('#0B0F19')
    ax.set_facecolor('#0B0F19')
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # Header / Title
    ax.text(50, 96, "SELLER-SHIELD AI — AUTONOMOUS LANGGRAPH MULTI-AGENT ARCHITECTURE", 
            fontsize=20, fontweight='bold', color='#10B981', ha='center', va='center')
    ax.text(50, 92.5, "17 Stateful Nodes with Checkpointing, Policy Guardrails, 1-Click Retention, and Human-in-the-Loop Safety", 
            fontsize=12, color='#94A3B8', ha='center', va='center')

    # Draw Stage Containers (Borders)
    stages = [
        ("STAGE 1: INGESTION & INTENT", 4, 18, 90, '#1E293B', '#38BDF8'),
        ("STAGE 2: ROUTING & POLICIES", 24, 26, 90, '#1E293B', '#F59E0B'),
        ("STAGE 3: RETENTION & ACTIONS", 52, 24, 90, '#1E293B', '#10B981'),
        ("STAGE 4: VERIFY, RESPOND & AUDIT", 78, 18, 90, '#1E293B', '#8B5CF6')
    ]

    for title, x, width, height, bg, border in stages:
        rect = patches.FancyBboxPatch((x, 5), width, height, boxstyle="round,pad=1,rounding_size=2",
                                      facecolor='#0F172A', edgecolor=border, linewidth=1.5, alpha=0.9)
        ax.add_patch(rect)
        ax.text(x + width/2, 92, title, fontsize=10, fontweight='bold', color=border, ha='center', va='center')

    # Helper for Nodes
    def draw_node(x, y, w, h, title, subtitle, is_key=False):
        fill_col = '#1E293B' if not is_key else '#064E3B'
        border_col = '#10B981' if is_key else '#334155'
        line_w = 2.0 if is_key else 1.0

        rect = patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.5,rounding_size=1.2",
                                      facecolor=fill_col, edgecolor=border_col, linewidth=line_w)
        ax.add_patch(rect)

        badge = "[KEY NODE]" if is_key else ""
        if badge:
            ax.text(x + w - 1, y + h - 1, badge, fontsize=7, fontweight='bold', color='#34D399', ha='right', va='top')

        ax.text(x + w/2, y + h*0.62, title, fontsize=9.5, fontweight='bold', color='#FFFFFF', ha='center', va='center')
        ax.text(x + w/2, y + h*0.32, subtitle, fontsize=7.5, color='#94A3B8', ha='center', va='center')

    # Helper for Arrows
    def draw_arrow(x1, y1, x2, y2, color='#64748B', style='->', lw=1.5, label=None):
        ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle=style, color=color, lw=lw, shrinkA=3, shrinkB=3, mutation_scale=12))
        if label:
            mx, my = (x1 + x2)/2, (y1 + y2)/2
            ax.text(mx, my + 1.2, label, fontsize=7.5, fontweight='bold', color=color, ha='center', va='bottom',
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='#0B0F19', edgecolor='none', alpha=0.8))

    # STAGE 1 NODES
    draw_node(6, 75, 14, 11, "1. node_load_memory", "Customer Trust & Prefs")
    draw_node(6, 52, 14, 11, "2. node_understand", "Intent & Sentiment Analysis")
    draw_node(6, 29, 14, 11, "3. node_resolve_order", "Match ORD-1002/1003")

    draw_arrow(13, 75, 13, 63, '#38BDF8')
    draw_arrow(13, 52, 13, 40, '#38BDF8')

    # STAGE 2 NODES
    draw_node(26, 78, 16, 9.5, "4. node_track", "Live Transit Milestones")
    draw_node(26, 65, 16, 9.5, "5. node_cancel_order", "Pre-Dispatch Zero Touch")
    draw_node(26, 50, 16, 10.5, "6. node_ask_reason", "Size, Color, or Defect")
    draw_node(26, 32, 16, 12, "7. node_policy_check", "7-Day & Hygiene Guard", is_key=True)
    draw_node(26, 15, 16, 11, "8. node_collect_evidence", "Photo / Vision Defect Analysis")

    # Connect Stage 1 to Stage 2
    draw_arrow(20, 36, 26, 82, '#64748B', label='Tracking')
    draw_arrow(20, 34, 26, 70, '#64748B', label='Cancel')
    draw_arrow(20, 32, 26, 55, '#38BDF8', label='Return/Swap')
    draw_arrow(34, 50, 34, 44, '#F59E0B')
    draw_arrow(34, 32, 34, 26, '#F59E0B', label='Damaged Item')

    # STAGE 3 NODES
    draw_node(54, 70, 20, 12, "9. node_retention", "1-Click Size Swap / +10% Wallet", is_key=True)
    draw_node(54, 52, 20, 11, "10. node_replacement_flow", "Warehouse Inventory Reallocation")
    draw_node(54, 34, 20, 11, "11. node_refund_flow", "Escrow Wallet Credit / Bank Transfer")
    draw_node(54, 15, 20, 12, "12. node_act", "Execute DB & Courier Dispatch", is_key=True)

    # Connect Stage 2 to Stage 3
    draw_arrow(42, 38, 54, 76, '#10B981', label='Valid Return')
    draw_arrow(42, 20, 54, 73, '#10B981', label='Evidence Verified')
    draw_arrow(64, 70, 64, 63, '#38BDF8', label='Accepts Swap')
    draw_arrow(64, 70, 71, 45, '#F59E0B', label='Wants Refund')
    draw_arrow(64, 52, 64, 27, '#10B981')
    draw_arrow(64, 34, 64, 27, '#10B981')

    # STAGE 4 NODES
    draw_node(80, 75, 14, 11, "13. node_verify", "Safety & Ledger Audit", is_key=True)
    draw_node(80, 56, 14, 11, "14. node_escalate", "Human-in-the-Loop Admin Queue", is_key=True)
    draw_node(80, 38, 14, 11, "15. node_respond", "Empathetic Human Reply + Quick Pills")
    draw_node(80, 22, 14, 9.5, "16. node_summarize_memory", "Update Customer Preference")
    draw_node(80, 9, 14, 9.5, "17. node_audit", "Immutable Compliance Ledger")

    # Connect Stage 3 to Stage 4
    draw_arrow(74, 21, 80, 80, '#8B5CF6')
    draw_arrow(87, 75, 87, 67, '#EF4444', label='Flagged')
    draw_arrow(87, 75, 87, 49, '#10B981', label='Approved')
    draw_arrow(87, 56, 87, 49, '#64748B')
    draw_arrow(42, 82, 80, 44, '#64748B') # from tracking to respond
    draw_arrow(42, 70, 80, 42, '#64748B') # from cancel to respond
    draw_arrow(87, 38, 87, 31.5, '#8B5CF6')
    draw_arrow(87, 22, 87, 18.5, '#8B5CF6')

    # Bottom Legend / Footer
    legend_y = 1.8
    ax.add_patch(patches.FancyBboxPatch((10, 0.5), 80, 2.8, boxstyle="round,pad=0.2", facecolor='#0F172A', edgecolor='#334155'))
    ax.text(20, legend_y, "■ Green: Retention & Sales Protection", fontsize=9, color='#10B981', fontweight='bold', va='center')
    ax.text(48, legend_y, "■ Amber/Blue: Policy & State Transitions", fontsize=9, color='#F59E0B', fontweight='bold', va='center')
    ax.text(78, legend_y, "■ Purple: Verification & Safe Response", fontsize=9, color='#8B5CF6', fontweight='bold', va='center')

    plt.tight_layout()
    plt.savefig(output_png, facecolor=fig.get_facecolor(), edgecolor='none', bbox_inches='tight')
    if output_svg:
        plt.savefig(output_svg, facecolor=fig.get_facecolor(), edgecolor='none', bbox_inches='tight')
    plt.close()
    print(f"Diagram successfully saved to {output_png}")
    if output_svg:
        print(f"SVG diagram successfully saved to {output_svg}")

if __name__ == "__main__":
    png_path = os.path.abspath(r"c:\sellershield\langgraph_architecture.png")
    svg_path = os.path.abspath(r"c:\sellershield\langgraph_architecture.svg")
    generate_architecture_diagram(png_path, svg_path)
