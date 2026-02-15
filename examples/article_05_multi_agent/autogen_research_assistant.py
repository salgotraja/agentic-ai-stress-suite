#!/usr/bin/env python3
"""AutoGen implementation of research assistant multi-agent workflow.

This script demonstrates AutoGen's GroupChat pattern for collaborative research:
1. Topic Refiner: Takes broad topic, refines to 3-5 specific questions
2. Paper Finder: Searches for relevant papers/docs using tools
3. Insight Extractor: Analyzes content, extracts key findings
4. Report Compiler: Synthesizes insights into structured markdown report

Teaching note: AutoGen vs LangGraph vs CrewAI
----------------------------------------------
We've now seen three major agent frameworks. Key differences:

**AutoGen:**
- Focus: Multi-turn conversations, human-in-the-loop
- Pattern: GroupChat with speaker selection
- Strength: Research, collaborative problem-solving
- Learning curve: Medium (conversation-based abstraction)
- Control: Medium (less than LangGraph, more than CrewAI)

**LangGraph:**
- Focus: Custom workflows, state machines
- Pattern: StateGraph with nodes/edges
- Strength: Complex routing, full control
- Learning curve: Steep (graph theory required)
- Control: Maximum (full graph topology)

**CrewAI:**
- Focus: Standard workflows, task delegation
- Pattern: Agent + Task + Crew
- Strength: Rapid prototyping, simple workflows
- Learning curve: Gentle (intuitive abstractions)
- Control: Minimum (opinionated patterns)

When to use AutoGen:
- Research workflows (literature review, analysis)
- Multi-agent conversations (debate, consensus)
- Human-in-the-loop (UserProxyAgent for approval)
- Code generation with feedback loops

When to use LangGraph:
- Custom orchestration logic
- Complex conditional routing
- Full state observability
- Performance-critical applications

When to use CrewAI:
- Standard patterns (research, write, review)
- Rapid prototyping
- Beginner-friendly projects

For this demo:
- We implement research assistant in AutoGen
- Compare with LangGraph's researcher-writer-critic
- Show AutoGen's GroupChat and conversation patterns

Usage:
    python autogen_research_assistant.py --topic "RAG evaluation metrics"
    python autogen_research_assistant.py --topic "GraphRAG" --depth comprehensive
    python autogen_research_assistant.py --compare  # Show framework comparison
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


def print_separator(char: str = "=", length: int = 80) -> None:
    """Print visual separator."""
    print(char * length)


def show_autogen_patterns() -> None:
    """
    Display AutoGen key patterns and concepts.

    Teaching note: This shows AutoGen's unique approach to multi-agent systems.
    """
    print("AUTOGEN KEY PATTERNS")
    print_separator()
    print()

    print("1. CONVERSABLE AGENT")
    print("-" * 80)
    print("AutoGen's base agent abstraction:")
    print("```python")
    print("from autogen import ConversableAgent")
    print()
    print("agent = ConversableAgent(")
    print("    name='ResearchAgent',")
    print("    system_message='You are a research specialist...',")
    print("    llm_config={'model': 'gpt-4'},")
    print("    human_input_mode='NEVER',  # Or 'ALWAYS', 'TERMINATE'")
    print(")")
    print("```")
    print()
    print("Key features:")
    print("  - Maintains conversation history automatically")
    print("  - Can call functions/tools")
    print("  - Supports human-in-the-loop with UserProxyAgent")
    print()

    print("2. GROUP CHAT")
    print("-" * 80)
    print("AutoGen's multi-agent coordination pattern:")
    print("```python")
    print("from autogen import GroupChat, GroupChatManager")
    print()
    print("group_chat = GroupChat(")
    print("    agents=[refiner, finder, extractor, compiler],")
    print("    messages=[],")
    print("    max_round=10,")
    print("    speaker_selection_method='auto',  # Or 'round_robin', 'manual'")
    print(")")
    print()
    print("manager = GroupChatManager(group_chat, llm_config=llm_config)")
    print("```")
    print()
    print("Comparison to other frameworks:")
    print("  - LangGraph: Manual graph with explicit edges")
    print("  - CrewAI: Sequential/parallel/hierarchical process")
    print("  - AutoGen: Conversation-based with speaker selection")
    print()

    print("3. SPEAKER SELECTION")
    print("-" * 80)
    print("AutoGen automatically selects next speaker:")
    print()
    print("Methods:")
    print("  - 'auto': LLM decides based on conversation context")
    print("  - 'round_robin': Fixed order (like CrewAI sequential)")
    print("  - 'manual': Custom function")
    print("  - 'random': Random selection")
    print()
    print("Example custom selection:")
    print("```python")
    print("def custom_speaker_selection(last_speaker, group_chat):")
    print("    if 'search' in group_chat.messages[-1]['content'].lower():")
    print("        return paper_finder  # Trigger search agent")
    print("    return None  # Let auto handle it")
    print("```")
    print()

    print("4. FUNCTION CALLING")
    print("-" * 80)
    print("AutoGen agents can call functions/tools:")
    print("```python")
    print("def search_papers(query: str) -> str:")
    print("    # Search implementation")
    print("    return results")
    print()
    print("agent = ConversableAgent(")
    print("    name='Searcher',")
    print("    llm_config={")
    print("        'functions': [")
    print("            {")
    print("                'name': 'search_papers',")
    print("                'description': 'Search for research papers',")
    print("                'parameters': {...}")
    print("            }")
    print("        ]")
    print("    }")
    print(")")
    print()
    print("agent.register_function(")
    print("    function_map={'search_papers': search_papers}")
    print(")")
    print("```")
    print()

    print("5. HUMAN-IN-THE-LOOP")
    print("-" * 80)
    print("UserProxyAgent enables human approval:")
    print("```python")
    print("user_proxy = UserProxyAgent(")
    print("    name='HumanReviewer',")
    print("    human_input_mode='ALWAYS',  # Ask before every action")
    print("    code_execution_config=False,  # Disable code exec")
    print(")")
    print()
    print("# Start conversation - will pause for human input")
    print("user_proxy.initiate_chat(")
    print("    agent,")
    print("    message='Research GraphRAG'")
    print(")")
    print("```")
    print()
    print("Human input modes:")
    print("  - 'ALWAYS': Pause for approval before each action")
    print("  - 'NEVER': Fully autonomous")
    print("  - 'TERMINATE': Only ask when ready to terminate")
    print()

    print_separator()


def show_framework_comparison() -> None:
    """
    Compare AutoGen with LangGraph and CrewAI.

    Teaching note: Three frameworks, three philosophies.
    """
    print("FRAMEWORK COMPARISON: AutoGen vs LangGraph vs CrewAI")
    print_separator()
    print()

    print("1. ORCHESTRATION PATTERN")
    print("-" * 80)
    print("AutoGen:")
    print("  - GroupChat with speaker selection")
    print("  - Conversation-based coordination")
    print("  - Agents decide who speaks next")
    print()
    print("LangGraph:")
    print("  - StateGraph with nodes/edges")
    print("  - Explicit routing logic")
    print("  - Developer controls flow")
    print()
    print("CrewAI:")
    print("  - Task-based sequential/parallel")
    print("  - Fixed workflow patterns")
    print("  - Minimal routing control")
    print()

    print("2. USE CASE FIT")
    print("-" * 80)
    print("AutoGen best for:")
    print("  ✓ Research workflows (literature review, analysis)")
    print("  ✓ Multi-agent conversations (debate, brainstorming)")
    print("  ✓ Human-in-the-loop (approval gates)")
    print("  ✓ Code generation with iterative feedback")
    print()
    print("LangGraph best for:")
    print("  ✓ Custom orchestration logic")
    print("  ✓ Complex conditional routing")
    print("  ✓ Full state observability")
    print("  ✓ Performance-critical applications")
    print()
    print("CrewAI best for:")
    print("  ✓ Standard workflows (research, write, review)")
    print("  ✓ Rapid prototyping")
    print("  ✓ Beginner-friendly projects")
    print()

    print("3. CODE COMPLEXITY")
    print("-" * 80)
    print("Research Assistant Workflow (4 agents):")
    print("  AutoGen: ~350 lines (GroupChat setup + agent definitions)")
    print("  LangGraph: ~400 lines (StateGraph + nodes + routing)")
    print("  CrewAI: ~250 lines (Agent + Task + Crew)")
    print()
    print("Verdict:")
    print("  - CrewAI simplest (but least flexible)")
    print("  - AutoGen medium (conversation-based)")
    print("  - LangGraph most code (but most control)")
    print()

    print("4. LEARNING CURVE")
    print("-" * 80)
    print("Difficulty (easiest to hardest):")
    print("  1. CrewAI: Intuitive Agent/Task/Crew")
    print("  2. AutoGen: Understand conversations and speaker selection")
    print("  3. LangGraph: Requires graph theory knowledge")
    print()

    print("5. FLEXIBILITY")
    print("-" * 80)
    print("Customization capability (least to most):")
    print("  1. CrewAI: Limited to built-in patterns")
    print("  2. AutoGen: Medium (custom speaker selection, reply functions)")
    print("  3. LangGraph: Maximum (any graph topology)")
    print()

    print("6. CONVERSATION HISTORY")
    print("-" * 80)
    print("AutoGen:")
    print("  - Automatic conversation tracking")
    print("  - Built-in message history")
    print("  - Agents see full conversation")
    print()
    print("LangGraph:")
    print("  - Manual state management")
    print("  - Developer controls what's passed")
    print("  - More explicit, more work")
    print()
    print("CrewAI:")
    print("  - Automatic task output passing")
    print("  - Limited conversation context")
    print("  - Simple but less control")
    print()

    print("=" * 80)
    print("DECISION GUIDE")
    print("=" * 80)
    print()
    print("Choose AutoGen when:")
    print("  → Multi-agent conversation is natural model")
    print("  → Need human-in-the-loop approval")
    print("  → Research/analysis workflows")
    print("  → Want automatic conversation tracking")
    print()
    print("Choose LangGraph when:")
    print("  → Need complex conditional routing")
    print("  → Full state control required")
    print("  → Building reusable agent libraries")
    print("  → Performance tuning is priority")
    print()
    print("Choose CrewAI when:")
    print("  → Standard patterns sufficient")
    print("  → Rapid prototyping needed")
    print("  → Team has limited framework experience")
    print("  → Want minimal code maintenance")
    print()
    print_separator()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="AutoGen research assistant demonstration")
    parser.add_argument(
        "--topic",
        type=str,
        default="RAG evaluation metrics",
        help="Research topic",
    )
    parser.add_argument(
        "--depth",
        type=str,
        default="quick",
        choices=["quick", "comprehensive"],
        help="Research depth (quick: 1-2 sources, comprehensive: 5+ sources)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Show framework comparison (AutoGen vs LangGraph vs CrewAI)",
    )
    parser.add_argument(
        "--patterns",
        action="store_true",
        help="Show AutoGen key patterns and concepts",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute workflow (requires OpenAI API key)",
    )

    args = parser.parse_args()

    print_separator()
    print("AutoGen Research Assistant")
    print_separator()
    print()

    if args.compare:
        show_framework_comparison()
        return 0

    if args.patterns:
        show_autogen_patterns()
        return 0

    # Show conceptual workflow
    print(f"Topic: {args.topic}")
    print(f"Depth: {args.depth}")
    print()

    print_separator("-")
    print("RESEARCH WORKFLOW (AutoGen GroupChat)")
    print_separator("-")
    print()

    print("Agent Pipeline:")
    print("  1. Topic Refiner → Breaks topic into 3-5 specific questions")
    print("  2. Paper Finder → Searches for relevant papers/docs")
    print("  3. Insight Extractor → Analyzes content, finds patterns")
    print("  4. Report Compiler → Synthesizes markdown report")
    print()

    print("AutoGen GroupChat Pattern:")
    print("  - Agents participate in conversation")
    print("  - Speaker selection: auto (LLM decides who speaks next)")
    print("  - Conversation history: maintained automatically")
    print("  - Termination: when Report Compiler finishes")
    print()

    if not args.execute:
        print_separator()
        print("NOTE: This is a demonstration showing AutoGen patterns.")
        print("To actually execute, run with --execute flag.")
        print()
        print("Setup required:")
        print("  1. Set OPENAI_API_KEY in .env.local")
        print("  2. Configure AutoGen LLM settings")
        print()
        print("For framework comparison:")
        print("  python autogen_research_assistant.py --compare")
        print()
        print("For AutoGen patterns:")
        print("  python autogen_research_assistant.py --patterns")
        print_separator()
        return 0

    print("Execution mode not yet implemented.")
    print("This task focuses on framework comparison and pattern demonstration.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
