import datetime
from dataclasses import dataclass, field, InitVar
from typing import List, Optional, Dict, Any, Tuple
import dateutil.parser
from dataclasses import dataclass, field, InitVar

from google.genai import types

@dataclass
class TimeSlot:
    """Represents a single 30-minute time slot."""
    start_time: datetime.datetime
    end_time: datetime.datetime
    
    # InitVars: These are passed to __init__ and __post_init__
    # but are NOT stored as attributes on the class instance.
    work_start: InitVar[Optional[datetime.time]] = None
    work_end: InitVar[Optional[datetime.time]] = None
    
    # Regular fields
    status: str = 'available'
    title: Optional[str] = None
    description: Optional[str] = None
    people_involved: List[str] = field(default_factory=list)

    def __post_init__(self, work_start: Optional[datetime.time], work_end: Optional[datetime.time]):
        """
        Runs after the object is created.
        Uses work_start and work_end to set the initial status.
        """
        # Set status as busy if the slot is outside working hours
        if work_start is not None and work_end is not None:
            if not self.is_during_workday(work_start, work_end):
                self.status = 'busy'

    def is_during_workday(self, work_start: datetime.time, work_end: datetime.time) -> bool:
        """
        Checks if the time slot falls completely within the given workday hours.

        Args:
            work_start (datetime.time): The time the workday begins (e.g., datetime.time(9, 0)).
            work_end (datetime.time): The time the workday ends (e.g., datetime.time(17, 0)).
        """
        # Can't handle work_start after work_end (e.g. Nocturnal shifts)

        # Get just the time components of the slot
        slot_start_time = self.start_time.time()
        slot_end_time = self.end_time.time()
        
        # Check if the slot starts on or after the workday begins
        starts_after_begin = (slot_start_time >= work_start)
        
        # Check if the slot ends on or before the workday finishes
        ends_before_finish = (slot_end_time <= work_end)
        
        # Both conditions must be true
        return starts_after_begin and ends_before_finish

class Calendar:
    """
    Manages a collection of TimeSlot objects, optimized for
    fast lookup by their start time.
    """
    
    def __init__(self,
                 start_date: datetime.datetime,
                 end_date: datetime.datetime,
                 work_start: Optional[datetime.time] = None,
                 work_end: Optional[datetime.time] = None,
                 time_increment_minutes: int = 30):
        """
        Generates and stores all time slots between two dates.
        """
        self.slots: Dict[datetime.datetime, TimeSlot] = {}
        self.time_delta = datetime.timedelta(minutes=time_increment_minutes)
        self.time_increment_minutes = time_increment_minutes

        current_time = start_date
        
        while current_time < end_date:
            end_time = current_time + self.time_delta
            
            # Create the slot, passing workday hours to its constructor
            slot = TimeSlot(
                start_time=current_time,
                end_time=end_time,
                work_start=work_start,
                work_end=work_end
            )
            
            # Use the start_time as the key for the dictionary
            self.slots[current_time] = slot
            
            # Move to the next slot
            current_time = end_time

    def round_to_nearest_slot(self, time_to_round: datetime.datetime) -> datetime.datetime:
        """
        Rounds a datetime object down to the nearest slot increment.
        e.g., 10:05 -> 10:00
        e.g., 10:35 -> 10:30
        e.g., 10:59 -> 10:30
        """
        total_minutes = time_to_round.hour * 60 + time_to_round.minute
        
        # Use modulo to find how many minutes past the last slot we are
        remainder_minutes = total_minutes % self.time_increment_minutes
        
        # Subtract those minutes to get the "floor"
        rounded_time = time_to_round - datetime.timedelta(minutes=remainder_minutes)
        
        # Return the rounded time with seconds and microseconds zeroed out
        return rounded_time.replace(second = 0, microsecond = 0)
 
    def get_slot_at(self, requested_time: datetime.datetime) -> Optional[TimeSlot]:
        """
        Fetches a single TimeSlot using its exact start time.
        Returns None if no slot exists at that time.
        """
        # Use the rounding function to find the correct dictionary key
        rounded_key = self.round_to_nearest_slot(requested_time)
        
        # Now do the same fast lookup as before
        return self.slots.get(rounded_key)

    def get_slots_for_day(self, day: datetime.date) -> List[TimeSlot]:
        """
        Returns a list of all TimeSlot objects for a specific date.
        """
        # Note: This is fast because Python dicts are ordered.
        # We can make it faster by finding the start, but this is cleaner.
        daily_slots = []
        for slot_time, slot in self.slots.items():
            if slot_time.date() == day:
                daily_slots.append(slot)
            elif slot_time.date() > day:
                # Stop iterating once we've passed the day
                break
        return daily_slots

    def book_slot(self, time_to_book: datetime.datetime, title: str) -> bool:
        """Books a slot if it's available."""
        slot = self.get_slot_at(time_to_book)
        if slot and slot.status == 'available':
            slot.status = 'busy'
            slot.title = title
            return True
        return False
    

######### Agents #########

def create_agent_system_prompt(persona: str, task: str) -> str:
    system_prompt = f"""
You are a professional scheduling agent. Your sole purpose is to represent your 
boss in this interaction. 

You DO NOT have your own personality. Your entire behavioral style, priorities, 
quirks, and communication patterns are a direct and perfect reflection of the 
persona of your boss, described below. You must act *exactly* as they would 
act if they were managing this interaction themselves.

Read the persona carefully. Your boss's goals and frustrations are your goals 
and frustrations.

--- PERSONA OF YOUR BOSS ---
{persona}
--- END PERSONA ---

Your sole and immediate objective is to complete the following task. 
You must execute this task according to your boss's behavioral style.

--- YOUR CURRENT TASK ---
{task}
--- END TASK ---
"""
    return system_prompt.strip()

def agent_chat(
    client,
    system_prompt: str,
    history: list = [""], 
    model_name: str = "gemini-2.5-flash",
    thinking_budget: int = 0,
    temperature: float = 0.7,
):
    full_conversation = history

    generate_content_config = types.GenerateContentConfig(
        thinking_config = types.ThinkingConfig(thinking_budget = thinking_budget),
        system_instruction = system_prompt,
        temperature = temperature,
    )

    response = client.models.generate_content(
        model = model_name,
        contents = full_conversation, 
        config = generate_content_config
    )

    if response.text:
        message = response.text
    else:
        message = ""

    return message