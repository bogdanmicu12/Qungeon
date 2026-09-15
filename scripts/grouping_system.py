class Group:
    """Represents a group of objects in the game, which is used for visualizing entangled states."""
    def __init__(self):
        """Initializes a new group with no objects and no states."""
        self.objects = []
        self.states = {}  # correlation histogram; empty until an effect is applied

class GroupingSystem:
    """Manages groups of objects and their merging in the game."""
    def __init__(self):
        """Initializes the grouping system with an empty list of groups and a count tracker."""
        self.count = 0
        self.groups = []

    def find(self, obj):
        """Finds and returns the group containing the specified object."""
        for group in self.groups:
            if obj in group.objects:
                return group
        return None

    def merge(self, group1, group2):
        """Merges two groups into one."""
        if group1 != group2 and group1 in self.groups and group2 in self.groups:
            self.groups.remove(group2)
            for obj in group2.objects:
                obj.group = group1
            group1.objects.extend(group2.objects)

    def add(self, obj, group=None):
        """Adds an object to an existing group or creates a new group for the object."""
        if group:
            group.objects.append(obj)
            return group
        else:
            new_group = Group()
            new_group.objects.append(obj)
            self.groups.append(new_group)
            return new_group

    def join(self, obj, reference_obj):
        """Joins the group of one object with the group of another object."""
        self.merge(obj.group, reference_obj.group)
        return obj.group