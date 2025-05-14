"""
Temperature conversion utilities for the AC control system.
Handles conversion between Celsius and Fahrenheit.
"""

def celsius_to_fahrenheit(celsius):
    """
    Convert temperature from Celsius to Fahrenheit
    
    Args:
        celsius (float): Temperature in Celsius
        
    Returns:
        float: Temperature in Fahrenheit
    """
    if celsius is None:
        return None
    return (celsius * 9/5) + 32


def fahrenheit_to_celsius(fahrenheit):
    """
    Convert temperature from Fahrenheit to Celsius
    
    Args:
        fahrenheit (float): Temperature in Fahrenheit
        
    Returns:
        float: Temperature in Celsius
    """
    if fahrenheit is None:
        return None
    return (fahrenheit - 32) * 5/9


def format_temp_for_display(temp_celsius, use_fahrenheit=True, include_unit=True):
    """
    Format temperature for display with appropriate unit
    
    Args:
        temp_celsius (float): Temperature in Celsius
        use_fahrenheit (bool): Whether to convert to Fahrenheit
        include_unit (bool): Whether to include unit symbol
        
    Returns:
        str: Formatted temperature string
    """
    if temp_celsius is None:
        return "N/A"
        
    if use_fahrenheit:
        temp = celsius_to_fahrenheit(temp_celsius)
        unit = "°F" if include_unit else ""
    else:
        temp = temp_celsius
        unit = "°C" if include_unit else ""
        
    # Format to 1 decimal place
    return f"{temp:.1f}{unit}"